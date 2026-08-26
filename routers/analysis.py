"""Analysis endpoints: single image, deep marketplace analysis, image parsing.

Block A wiring:
- A.2 idempotency via X-Request-ID (cached verdicts are replayed, not recomputed),
- A.3 whole-path deadline budget,
- A.1/A.4/A.6 resilient gateway with provider failover, strict validation,
  queueing on total outage and manual-review degradation.
"""

import asyncio
import base64
import logging
import uuid
from io import BytesIO

from fastapi import APIRouter, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse

from core.config import (
    DEEP_ANALYSIS_TIMEOUT_SECONDS,
    MAX_IMAGE_UPLOAD_BYTES,
    get_api_key_for_provider,
    get_secret,
    settings,
)
from core.deadline import Deadline, DeadlineExceeded, reset_deadline, set_deadline
from database import cache_get_result, cache_put_result, enqueue_retry, save_check
from llm_provider import ProviderType
from models.schemas import AnalysisResult

logger = logging.getLogger(__name__)
router = APIRouter(tags=["analysis"])

MANUAL_REVIEW_VERDICT = "ТРЕБУЕТ РУЧНОЙ ПРОВЕРКИ"


async def read_upload(file: UploadFile, request: Request, max_bytes: int) -> bytes:
    """Read an uploaded file enforcing the size limit (413 on exceed)."""
    content_length = request.headers.get("content-length")
    if content_length and int(content_length) > max_bytes * 2:
        raise HTTPException(status_code=413, detail="Payload Too Large")
    data = await file.read()
    if len(data) > max_bytes:
        raise HTTPException(
            status_code=413,
            detail=f"File too large (max {max_bytes // (1024 * 1024)} MB)"
        )
    return data


def _resolve_request_id(request: Request, provided: str | None) -> str:
    """Client-supplied id wins; otherwise generate one. Returned to the client."""
    rid = (provided or request.headers.get("x-request-id") or "").strip()
    if len(rid) > 64 or any(c in rid for c in "\r\n\x00"):
        raise HTTPException(status_code=400, detail="Invalid X-Request-ID")
    return rid or uuid.uuid4().hex


def _estimated_wait_seconds() -> int:
    """Rough ETA for the retry queue: poll interval * max attempts."""
    return int(settings.retry_queue_poll_seconds * settings.retry_queue_max_attempts)


@router.post("/parse-image")
async def parse_image(request: Request, url: str = Form(...)):
    """Unified marketplace image parsing (no dependency on the LLM provider)."""
    from services import tenancy
    from services.marketplace_image_fetcher import parse_marketplace_image

    await tenancy.require_ctx(request, min_role="viewer")
    try:
        return await parse_marketplace_image(url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/analyze")
async def analyze(
    request: Request,
    original: UploadFile = File(...),
    suspect: UploadFile = File(...),
    url: str = Form(""),
    brand: str = Form(""),
    marketplace: str = Form(""),
    price_original: int = Form(0, ge=0),
    price_suspect: int = Form(0, ge=0),
    seller: str = Form("", max_length=200),
    request_id: str = Form(None),
):
    """Single-pair analysis with idempotency, failover and queueing."""
    import core.llm_gateway as gateway
    from services import tenancy
    from telegram_alerts import send_telegram_alert

    rid = _resolve_request_id(request, request_id)
    # F.2/F.3: role gate + plan quota (cached replays don't consume quota).
    ctx = await tenancy.require_ctx(request, min_role="analyst")

    # A.2 — replay a cached verdict instead of paying for the LLM twice.
    cached = await cache_get_result(rid, ttl_hours=settings.idempotency_ttl_hours)
    if cached is not None:
        return JSONResponse(
            content=cached,
            headers={"X-Request-ID": rid, "X-Cache": "HIT"},
        )

    if not get_api_key_for_provider(settings.provider) and not (
        get_api_key_for_provider("gemini") or get_api_key_for_provider("grok")
    ):
        raise HTTPException(status_code=500, detail="API key not configured")

    # F.3 — monthly checks quota of the caller's tariff plan.
    await tenancy.ensure_checks_quota(ctx.tenant_id, requested=1)
    tenant_id = ctx.tenant_id

    if brand and len(brand) > 200:
        raise HTTPException(status_code=400, detail="Brand name too long (max 200 chars)")

    original_bytes = await read_upload(original, request, MAX_IMAGE_UPLOAD_BYTES)
    suspect_bytes = await read_upload(suspect, request, MAX_IMAGE_UPLOAD_BYTES)

    if len(original_bytes) == 0 or len(suspect_bytes) == 0:
        raise HTTPException(status_code=400, detail="Both images are required")

    meta = {
        "brand": brand,
        "marketplace": marketplace,
        "price_original": price_original,
        "price_suspect": price_suspect,
        "url": url,
    }

    # --- Block B: cheap forensic layers BEFORE any LLM spend -------------------
    from database import find_similar_suspect_hash, save_image_hash
    from forensics.ela import compute_ela
    from forensics.exif import extract_exif_flags
    from forensics.phash import compute_phash

    suspect_phash = compute_phash(suspect_bytes)
    reference_phash = compute_phash(original_bytes)
    ela = compute_ela(
        suspect_bytes,
        quality=settings.ela_quality,
        flag_threshold=settings.ela_flag_threshold,
    )
    _exif_subset, exif_flags_list = extract_exif_flags(suspect_bytes)

    # B.1 fast path: near-identical image already classified → instant verdict.
    if suspect_phash and not request.headers.get("x-force-recheck"):
        match = await find_similar_suspect_hash(
            suspect_phash, settings.phash_hamming_threshold
        )
        if match:
            from forensics.phash import similarity_percent

            result = {
                "verdict": match["verdict"],
                "confidence": match["confidence"] or 0,
                "summary": match["summary"] or "",
                "risk_level": "low",
                "indicators": [],
                "verdict_source": "phash_match",
                "provider": None,
                "phash": suspect_phash,
                "matched_hash_id": match["id"],
                "hamming_distance": match["hamming_distance"],
                "phash_similarity": similarity_percent(match["hamming_distance"]),
                "consensus": "not_needed",
                **gateway.prompt_fingerprint(meta),
            }
            logger.info(
                f"[{rid}] pHash fast path: distance={match['hamming_distance']} "
                f"→ '{match['verdict']}' without LLM call"
            )
            return await _finalize_analyze_response(
                rid=rid,
                result=result,
                source=None,
                original_bytes=original_bytes,
                suspect_bytes=suspect_bytes,
                reference_phash=reference_phash,
                suspect_phash=suspect_phash,
                ela=ela,
                exif_flags_list=exif_flags_list,
                url=url,
                brand=brand,
                marketplace=marketplace,
                price_original=price_original,
                price_suspect=price_suspect,
                seller=seller,
                tenant_id=tenant_id,
            )

    # A.3 — one deadline for the whole path.
    deadline = Deadline(settings.request_timeout_budget_seconds)
    token = set_deadline(deadline)
    try:
        try:
            result, source = await asyncio.wait_for(
                gateway.analyze_resilient(original_bytes, suspect_bytes, meta),
                timeout=deadline.remaining(),
            )
        except gateway.AllProvidersDownError as e:
            # A.6 — queue instead of 500; client polls /queue/{request_id}.
            await enqueue_retry(rid, {
                "original_b64": base64.b64encode(original_bytes).decode(),
                "suspect_b64": base64.b64encode(suspect_bytes).decode(),
                "meta": {k: v for k, v in meta.items() if k != "_correction"},
                "preferred_provider": None,
            })
            logger.warning(f"[{rid}] all providers down, queued ({len(e.attempts)} attempts)")
            return JSONResponse(
                status_code=202,
                headers={"X-Request-ID": rid},
                content={
                    "status": "queued",
                    "request_id": rid,
                    "poll_url": f"/api/v1/queue/{rid}",
                    "estimated_wait_seconds": _estimated_wait_seconds(),
                    "detail": "Все LLM-провайдеры временно недоступны, "
                              "анализ поставлен в очередь на повтор",
                },
            )
        except gateway.AllOutputsInvalidError as e:
            # A.4 — graceful degradation to manual review instead of 500.
            result = AnalysisResult.manual_review(
                "Модели вернули невалидный ответ; требуется ручная проверка эксперта"
            ).model_dump()
            source = {"provider": None, "verdict_source": "manual_review_fallback"}
            logger.error(f"[{rid}] all outputs invalid: {e}")
    finally:
        reset_deadline(token)

    # B.3 — multi-model consensus for borderline confidence band.
    result, consensus_meta = await gateway.run_consensus(
        result, source.get("provider"), original_bytes, suspect_bytes, meta
    )
    source.update(consensus_meta)

    return await _finalize_analyze_response(
        rid=rid,
        result=result,
        source=source,
        original_bytes=original_bytes,
        suspect_bytes=suspect_bytes,
        reference_phash=reference_phash,
        suspect_phash=suspect_phash,
        ela=ela,
        exif_flags_list=exif_flags_list,
        url=url,
        brand=brand,
        marketplace=marketplace,
        price_original=price_original,
        price_suspect=price_suspect,
        seller=seller,
        tenant_id=tenant_id,
    )


async def _finalize_analyze_response(
    rid: str,
    result: dict,
    source: dict | None,
    original_bytes: bytes,
    suspect_bytes: bytes,
    reference_phash: str | None,
    suspect_phash: str | None,
    ela: dict,
    exif_flags_list: list,
    *,
    url: str,
    brand: str,
    marketplace: str,
    price_original: int,
    price_suspect: int,
    seller: str = "",
    tenant_id: int = 1,
) -> JSONResponse:
    """Shared tail for the pHash fast path and the full LLM path (Block B)."""
    from core.verdict_engine import adjust_confidence_with_forensics, compute_final_score
    from database import cache_put_result, save_check, save_image_hash
    from forensics.phash import hamming_distance, similarity_percent
    from telegram_alerts import send_telegram_alert

    if source:
        result.update(source)

    phash_similarity = None
    if reference_phash and suspect_phash:
        phash_similarity = similarity_percent(hamming_distance(reference_phash, suspect_phash))

    price_ratio = (
        price_suspect / price_original if price_original and price_suspect else None
    )

    final_score, components = compute_final_score(
        llm_confidence=result.get("confidence"),
        phash_similarity=phash_similarity,
        ela_score=ela["ela_score"],
        exif_flag_count=len(exif_flags_list),
        price_ratio=price_ratio,
        weights=settings.composite_weights(),
        price_floor=settings.price_floor,
        price_ceiling=settings.price_ceiling,
    )

    verdict = result.get("verdict")
    adjusted_confidence = result.get("confidence")
    if source is None or source.get("verdict_source") == "llm_analysis":
        # B.4: LLM keeps the label, forensics modulate expressed certainty.
        adjusted_confidence = adjust_confidence_with_forensics(
            str(verdict), int(result.get("confidence") or 0), final_score
        )

    forensic_indicators = [
        {
            "factor": f["factor"],
            "score": int(f["score"]),
            "status": f["status"],
            "detail": f["detail"],
        }
        for f in exif_flags_list
    ]
    if ela["ela_flag"]:
        forensic_indicators.append({
            "factor": "ELA: следы редактирования",
            "score": 7,
            "status": "fail",
            "detail": (
                f"Error Level Analysis = {ela['ela_score']} (max_error "
                f"{ela['max_error']}) — локально неоднородное сжатие, "
                f"возможна склейка/ретушь фото"
            ),
        })

    result.update({
        "url": url,
        "brand": brand,
        "marketplace": marketplace,
        "price_original": price_original,
        "price_suspect": price_suspect,
        "seller": seller,
        "request_id": rid,
        "tenant_id": tenant_id,
        "phash": suspect_phash,
        "phash_similarity_reference": phash_similarity,
        "ela_score": ela["ela_score"],
        "ela_flag": ela["ela_flag"],
        "exif_flags": exif_flags_list,
        "final_score": final_score,
        "score_components": components,
        "confidence": adjusted_confidence,
        "indicators": list(result.get("indicators") or []) + forensic_indicators,
    })

    check_id = await save_check(result)
    await cache_put_result(rid, result, ttl_hours=settings.idempotency_ttl_hours)

    # D: open a workflow case for non-original verdicts + evidence artifacts.
    if check_id and verdict:
        from services.case_service import ensure_case_for_check

        await ensure_case_for_check(
            check_id=check_id,
            url=url,
            reference_b64=base64.b64encode(original_bytes).decode(),
            suspect_b64=base64.b64encode(suspect_bytes).decode(),
            verdict=str(verdict),
            capture_screenshot=bool(url),
        )

    if suspect_phash:
        await save_image_hash(
            suspect_phash,
            "suspect",
            verdict=str(verdict) if verdict else None,
            confidence=int(result.get("confidence") or 0),
            summary=str(result.get("summary") or ""),
            related_check_id=check_id or None,
            image_url=url or None,
        )
    if reference_phash:
        await save_image_hash(reference_phash, "reference", related_check_id=check_id or None)

    bot_token = get_secret(settings.telegram_bot_token)
    chat_id = settings.telegram_chat_id
    if verdict in ("ПОДДЕЛКА", "ПОДОЗРИТЕЛЬНО") and bot_token:
        asyncio.create_task(send_telegram_alert(
            bot_token=bot_token,
            chat_id=chat_id,
            verdict=str(verdict),
            confidence=int(result.get("confidence", 0)),
            brand=brand,
            url=url,
            summary=str(result.get("summary", "")),
            image_bytes=suspect_bytes
        ))

    return JSONResponse(
        content=result,
        headers={"X-Request-ID": rid, "X-Cache": "MISS"},
    )


@router.post("/analyze-deep")
async def analyze_deep(
    request: Request,
    url: str = Form(...),
    reference_image: str = Form(...),
    brand: str = Form(""),
    marketplace: str = Form(""),
    price_original: int = Form(0, ge=0),
    provider_name: str = Form(None),
):
    """Deep analysis: parse all images from a marketplace URL and aggregate results.

    Graceful degradation (A.6): when Playwright/browser is unavailable the
    endpoint falls back to plain httpx parsing and marks the response with
    ``partial_data=true`` + reason instead of failing with 501.
    """
    from PIL import Image
    from aggregator import ImageAggregator
    import core.llm_gateway as gateway
    from services import tenancy

    # F.2/F.3: role gate + monthly quota.
    ctx = await tenancy.require_ctx(request, min_role="analyst")
    await tenancy.ensure_checks_quota(ctx.tenant_id, requested=1)
    tenant_id = ctx.tenant_id

    effective_provider = (provider_name or settings.provider).strip().lower()
    try:
        effective_provider = ProviderType(effective_provider).value
    except ValueError:
        raise HTTPException(
            status_code=422,
            detail=f"Unsupported provider '{effective_provider}'. Allowed: gemini, grok"
        )

    api_key = get_api_key_for_provider(effective_provider)
    if not api_key:
        raise HTTPException(
            status_code=500,
            detail=f"API key for '{effective_provider}' not configured"
        )

    if brand and len(brand) > 200:
        raise HTTPException(status_code=400, detail="Brand name too long (max 200 chars)")

    try:
        reference_bytes = base64.b64decode(reference_image)
        img = Image.open(BytesIO(reference_bytes))
        if img.mode in ('RGBA', 'LA', 'P'):
            img = img.convert('RGB')
        img_buffer = BytesIO()
        img.save(img_buffer, format='JPEG')
        reference_bytes = img_buffer.getvalue()
    except Exception as e:
        logger.warning(f"Invalid reference image: {e}")
        raise HTTPException(status_code=400, detail="Invalid reference image")

    # --- Parsing with graceful degradation ------------------------------------
    parse_result = None
    partial_data = False
    partial_reason = None

    try:
        browser = None
        page = None
        try:
            from services.browser_service import (
                PLAYWRIGHT_AVAILABLE,
                BrowserSettings,
                MinimalBrowserService,
            )
            if PLAYWRIGHT_AVAILABLE:
                browser = MinimalBrowserService(BrowserSettings())
                await browser.start()          # may raise RuntimeError
                page = browser.page
        except RuntimeError as e:
            logger.warning(f"Browser unavailable, degrading to httpx parsing: {e}")
            partial_data = True
            partial_reason = "browser unavailable"
            browser = None

        try:
            from parsers.factory import get_parser
            parser = await get_parser(url, browser_page=page)
            parse_result = await asyncio.wait_for(
                parser.get_all_images(), timeout=DEEP_ANALYSIS_TIMEOUT_SECONDS
            )
        finally:
            if browser:
                await browser.close()
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Превышен таймаут парсинга страницы маркетплейса")
    except HTTPException:
        raise
    except ValueError as e:
        logger.error(f"Parser error: {e}")
        raise HTTPException(status_code=400, detail=str(e))

    if parse_result is None or getattr(parse_result, "error", None):
        error_text = getattr(parse_result, "error", "parsing failed")
        logger.error(f"Parser error: {error_text}")
        raise HTTPException(status_code=502, detail=f"Error parsing images: {error_text}")

    if not (parse_result.card_images or parse_result.review_images or parse_result.qa_images):
        partial_data = True
        partial_reason = partial_reason or "no review/QA images extracted (JS-only content)"

    # --- Aggregation through the resilient gateway -----------------------------
    aggregator = ImageAggregator(provider_name=effective_provider, api_key=api_key)

    deadline = Deadline(settings.request_timeout_budget_seconds)
    token = set_deadline(deadline)
    try:
        try:
            aggregated_result = await asyncio.wait_for(
                aggregator.analyze_all(
                    parse_result,
                    reference_bytes,
                    {
                        "brand": brand,
                        "marketplace": marketplace,
                        "price_original": price_original
                    }
                ),
                timeout=deadline.remaining(),
            )
        except (asyncio.TimeoutError, DeadlineExceeded):
            raise HTTPException(
                status_code=504,
                detail="Превышен общий таймаут глубокого анализа",
                headers={"Retry-After": "30"},
            )
    finally:
        reset_deadline(token)

    result_with_meta = {
        **aggregated_result.__dict__,
        "url": url,
        "brand": brand,
        "marketplace": marketplace,
        "price_original": price_original,
        "partial_data": partial_data,
        "tenant_id": tenant_id,
    }
    if partial_reason:
        result_with_meta["partial_reason"] = partial_reason
    await save_check(result_with_meta)

    bot_token = get_secret(settings.telegram_bot_token)
    chat_id = settings.telegram_chat_id
    if aggregated_result.final_verdict != 'ОРИГИНАЛ' and bot_token:
        from telegram_alerts import send_telegram_alert
        summary_text = (
            f"📊 FakeDetect — Глубокий анализ\n\n"
            f"URL: {url}\n"
            f"Бренд: {brand}\n"
            f"Вердикт: {aggregated_result.final_verdict}\n"
            f"Уверенность: {aggregated_result.final_confidence}%\n"
            f"Всего изображений: {aggregated_result.total_images}\n"
            f"Подозрительных: {aggregated_result.suspicious_count}\n\n"
            f"{aggregated_result.summary}"
        )
        asyncio.create_task(send_telegram_alert(
            bot_token=bot_token,
            chat_id=chat_id,
            verdict=aggregated_result.final_verdict,
            confidence=aggregated_result.final_confidence,
            brand=brand,
            url=url,
            summary=summary_text,
            image_bytes=None
        ))

    return result_with_meta




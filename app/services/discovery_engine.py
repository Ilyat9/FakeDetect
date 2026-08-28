"""Discovery Engine (Block C.4): autonomous brand monitoring.

Scan cycle for a brand watch:
1. search every marketplace x keyword (C.2),
2. upsert listings + TTL deduplication (C.3),
3. run NEW listings through the same forensic+LLM pipeline as /analyze,
4. accumulate findings and send a digest (Telegram; email stub) instead of
   spamming an alert per finding.
"""

import asyncio
import importlib
import base64
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from app.core.config import settings
from app.database import (
    get_brand_watch,
    get_recent_findings,
    listing_needs_recheck,
    save_check,
    save_image_hash,
    set_watch_run_state,
    update_listing_analysis,
    upsert_listing,
)
from app.forensics.ela import compute_ela
from app.forensics.exif import extract_exif_flags
from app.forensics.phash import compute_phash

logger = logging.getLogger(__name__)


def compute_next_run_at(cron_schedule: str) -> str:
    """Next fire time for a cron expression (APScheduler CronTrigger).

    Falls back to +24h on an invalid expression — the watch keeps running
    even with a broken schedule instead of being silently orphaned.
    """
    now = datetime.now(timezone.utc)
    try:
        from apscheduler.triggers.cron import CronTrigger

        trigger = CronTrigger.from_crontab(cron_schedule)
        next_fire = trigger.get_next_fire_time(None, now)
        if next_fire is None:
            raise ValueError("no next fire time")
        return next_fire.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"Invalid cron '{cron_schedule}' ({e}); defaulting to +24h")
        return (now + timedelta(hours=24)).strftime("%Y-%m-%d %H:%M:%S")


async def run_watch_scan(watch_id: int) -> Dict[str, Any]:
    """Full scan cycle for one brand watch. Returns summary counters."""
    watch = await get_brand_watch(watch_id)
    if not watch or not watch.get("is_active"):
        return {"status": "inactive_or_missing"}

    brand = watch["brand_name"]
    watch_tenant = int(watch.get("tenant_id") or 1)
    keywords = [k.strip() for k in (watch["keywords"] or "").split(",") if k.strip()]
    marketplaces = [m.strip() for m in (watch["marketplaces"] or "WB").split(",") if m.strip()]

    reference_bytes = _primary_reference(watch)
    stats: Dict[str, int] = {"found": 0, "new": 0, "skipped": 0, "analyzed": 0, "errors": 0}

    # A browser is shared per scan when available (Ozon/Yandex JS rendering).
    browser_page = None
    close_browser = None
    try:
        from app.services.browser_service import PLAYWRIGHT_AVAILABLE

        if PLAYWRIGHT_AVAILABLE:
            from app.services.browser_service import BrowserSettings, MinimalBrowserService

            service = MinimalBrowserService(BrowserSettings())
            try:
                await service.start()
                browser_page = service.page
                close_browser = service.close
            except RuntimeError as e:
                logger.warning(f"Discovery: browser unavailable ({e}), httpx-only mode")

        semaphore = asyncio.Semaphore(settings.discovery_concurrency)

        async def process(listing: Dict[str, Any]) -> None:
            async with semaphore:
                await _process_listing(
                    watch_id, brand, listing, reference_bytes, stats,
                    tenant_id=watch_tenant,
                )

        from app.services.discovery.search_parsers import search_marketplace

        tasks = []
        for marketplace in marketplaces:
            for keyword in keywords:
                found = await search_marketplace(
                    marketplace, keyword,
                    settings.discovery_max_listings_per_keyword,
                    browser_page=browser_page,
                )
                logger.info(
                    f"Discovery watch#{watch_id} '{brand}' [{marketplace}] "
                    f"'{keyword}': {len(found)} listings"
                )
                stats["found"] += len(found)
                for item in found:
                    fields = {k: v for k, v in item.items() if k != "url"}
                    listing_id, created = await upsert_listing(
                        watch_id, item["url"], tenant_id=watch_tenant, **fields
                    )
                    if created:
                        stats["new"] += 1
                    needs = await listing_needs_recheck(
                        watch_id, item["url"],
                        settings.recheck_original_days,
                        settings.recheck_suspicious_days,
                        settings.recheck_fake_days,
                    )
                    if not needs:
                        stats["skipped"] += 1
                        continue
                    item["_listing_id"] = listing_id
                    item["_marketplace"] = marketplace
                    tasks.append(asyncio.create_task(process(item)))

        if tasks:
            await asyncio.gather(*tasks)
    finally:
        if close_browser:
            await close_browser()

    await set_watch_run_state(
        watch_id,
        last_status=f"ok: {stats['analyzed']} analyzed, {stats['skipped']} skipped",
        next_run_at=compute_next_run_at(watch.get("cron_schedule") or "0 7 * * *"),
        mark_run=True,
    )

    digest_hours = int(watch.get("digest_interval_hours") or settings.digest_default_hours)
    await maybe_send_digest(watch_id, brand, digest_hours)
    stats.update({"status": "ok", "brand": brand})
    logger.info(f"Discovery watch#{watch_id} scan complete: {stats}")
    return stats


def _primary_reference(watch: Dict[str, Any]) -> Optional[bytes]:
    """Decode the first reference image of a watch."""
    try:
        images = json.loads(watch.get("reference_images") or "[]")
        if images:
            return base64.b64decode(images[0])
    except Exception as e:  # noqa: BLE001
        logger.error(f"Failed to decode reference image: {e}")
    return None


async def _process_listing(
    watch_id: int,
    brand: str,
    listing: Dict[str, Any],
    reference_bytes: Optional[bytes],
    stats: Dict[str, int],
    tenant_id: int = 1,
) -> None:
    """Analyze one discovered listing through the forensic+LLM pipeline."""
    url = listing["url"]
    listing_id = listing.get("_listing_id") or 0
    marketplace = listing.get("_marketplace", "")
    meta = {
        "brand": brand,
        "marketplace": marketplace,
        "url": url,
        "price_original": 0,
        "price_suspect": int(listing["price"]) if listing.get("price") else 0,
    }

    # Fetch the suspect product photo (SSRF-safe, existing fetcher).
    try:
        from app.services.marketplace_image_fetcher import parse_marketplace_image

        data = await parse_marketplace_image(url)
        suspect_bytes = base64.b64decode(data["image_base64"])
    except Exception as e:  # noqa: BLE001
        logger.warning(f"[{brand}] listing fetch failed ({url}): {e}")
        await update_listing_analysis(listing_id, None, None, status="error")
        stats["errors"] += 1
        return

    if reference_bytes is None:
        logger.warning(f"[{brand}] watch#{watch_id} has no reference image; cannot analyze")
        await update_listing_analysis(listing_id, None, None, status="error")
        return

    # Forensic layers (same as /analyze).
    from app.core import llm_gateway as gateway

    suspect_phash = compute_phash(suspect_bytes)
    ela = compute_ela(
        suspect_bytes,
        quality=settings.ela_quality,
        flag_threshold=settings.ela_flag_threshold,
    )
    _exif_subset, exif_flags_list = extract_exif_flags(suspect_bytes)

    verdict_source = "llm_analysis"
    source: Optional[Dict[str, Any]] = None
    result: Dict[str, Any]

    # B.1 fast path: identical/similar image already classified.
    matched = (
        await importlib.import_module("app.database").find_similar_suspect_hash(
            suspect_phash, settings.phash_hamming_threshold
        )
        if suspect_phash
        else None
    )

    if matched:
        result = {
            "verdict": matched["verdict"],
            "confidence": matched["confidence"] or 0,
            "summary": matched["summary"] or "",
            "risk_level": "low",
            "indicators": [],
            "phash": suspect_phash,
            **gateway.prompt_fingerprint(meta),
        }
        verdict_source = "phash_match"
    else:
        deadline_token = None
        from app.core.deadline import Deadline, reset_deadline, set_deadline

        deadline = Deadline(settings.request_timeout_budget_seconds)
        deadline_token = set_deadline(deadline)
        try:
            try:
                raw, src = await asyncio.wait_for(
                    gateway.analyze_resilient(reference_bytes, suspect_bytes, meta),
                    timeout=deadline.remaining(),
                )
                raw, consensus_meta = await gateway.run_consensus(
                    raw, src.get("provider"), reference_bytes, suspect_bytes, meta
                )
                src.update(consensus_meta)
                result = {**raw}
                source = src
            except Exception as e:  # noqa: BLE001 - includes AllProviders* errors
                logger.warning(f"[{brand}] analysis failed for {url}: {e}")
                await update_listing_analysis(listing_id, None, None, status="error")
                stats["errors"] += 1
                return
        finally:
            if deadline_token is not None:
                reset_deadline(deadline_token)

    from app.core.verdict_engine import compute_final_score

    final_score, components = compute_final_score(
        llm_confidence=result.get("confidence"),
        ela_score=ela["ela_score"],
        exif_flag_count=len(exif_flags_list),
        weights=settings.composite_weights(),
    )

    result.update({
        "url": url,
        "brand": brand,
        "marketplace": marketplace,
        "seller": listing.get("seller"),
        "price_suspect": meta["price_suspect"],
        "ela_score": ela["ela_score"],
        "ela_flag": ela["ela_flag"],
        "exif_flags": exif_flags_list,
        "final_score": final_score,
        "score_components": components,
        "phash": suspect_phash,
        "verdict_source": verdict_source,
        "tenant_id": tenant_id,
    })

    check_id = await save_check(result)
    if suspect_phash:
        await save_image_hash(
            suspect_phash, "suspect",
            verdict=str(result.get("verdict")),
            confidence=int(result.get("confidence") or 0),
            summary=str(result.get("summary") or ""),
            related_check_id=check_id or None,
            image_url=url,
        )
    await update_listing_analysis(
        listing_id, str(result.get("verdict")), int(result.get("confidence") or 0),
    )
    stats["analyzed"] += 1

    # D: workflow case + evidence artifacts for non-original verdicts.
    if check_id and result.get("verdict"):
        from app.services.case_service import ensure_case_for_check

        await ensure_case_for_check(
            check_id=check_id,
            url=url,
            reference_b64=base64.b64encode(reference_bytes).decode() if reference_bytes else None,
            suspect_b64=base64.b64encode(suspect_bytes).decode(),
            verdict=str(result["verdict"]),
            capture_screenshot=bool(url),
        )


async def maybe_send_digest(watch_id: int, brand: str, digest_interval_hours: int) -> bool:
    """Send Telegram + (if configured) email digests of recent findings once
    the digest window elapsed."""
    from app.core.config import get_secret, smtp_configured
    from app.telegram_alerts import send_telegram_alert

    findings = await get_recent_findings(watch_id, since_hours=digest_interval_hours)

    watch = await get_brand_watch(watch_id)
    last_digest = (watch or {}).get("last_digest_at")
    if not findings:
        return False
    if last_digest:
        try:
            elapsed_h = (
                datetime.now(timezone.utc)
                - datetime.strptime(str(last_digest)[:19], "%Y-%m-%d %H:%M:%S")
                .replace(tzinfo=timezone.utc)
            ).total_seconds() / 3600.0
            if elapsed_h < digest_interval_hours * 0.95:
                return False  # digest already sent within the window
        except ValueError:
            pass

    fakes = [f for f in findings if f["verdict"] == "ПОДДЕЛКА"]
    suspicious = [f for f in findings if f["verdict"] == "ПОДОЗРИТЕЛЬНО"]
    text = build_digest_text(brand, findings)

    bot_token = get_secret(settings.telegram_bot_token)
    chat_id = settings.telegram_chat_id
    sent = False
    if bot_token and chat_id:
        sent = await send_telegram_alert(
            bot_token=bot_token,
            chat_id=chat_id,
            verdict="ПОДДЕЛКА" if fakes else "ПОДОЗРИТЕЛЬНО",
            confidence=int(findings[0]["confidence"] or 0),
            brand=brand,
            url=fakes[0]["url"] if fakes else (suspicious[0]["url"] if suspicious else ""),
            summary=text,
            image_bytes=None,
        )
    else:
        logger.info(f"[{brand}] digest (Telegram not configured):\n{text}")

    digest_email = (watch or {}).get("digest_email")
    if digest_email:
        if smtp_configured():
            from app.email_alerts import render_digest_html, send_digest_email

            html_body = render_digest_html(brand, fakes, suspicious)
            await send_digest_email(
                to_email=digest_email,
                subject=f"FakeDetect: дайджест «{brand}» — "
                        f"{len(fakes)} подделок, {len(suspicious)} подозрительных",
                html_body=html_body,
                text_body=text,
            )
        else:
            # C-C4: this watch has an email digest recipient configured, but
            # SMTP itself isn't set up in this environment — say so loudly
            # instead of silently sending nothing (the old stub's behavior).
            logger.warning(
                f"[{brand}] watch has digest_email={digest_email} but SMTP_HOST/"
                f"SMTP_FROM_EMAIL are not configured — email digest NOT sent"
            )

    # Mark the window as served even without Telegram configured, so scans
    # don't re-prepare the same digest every tick.
    await set_watch_run_state(watch_id, digest_sent=True)
    return sent


def build_digest_text(brand: str, findings: List[Dict[str, Any]]) -> str:
    """Human-readable digest body (HTML-escaped by telegram_alerts)."""
    fakes = [f for f in findings if f["verdict"] == "ПОДДЕЛКА"]
    suspicious = [f for f in findings if f["verdict"] == "ПОДОЗРИТЕЛЬНО"]
    lines = [
        f"📰 FakeDetect — Дайджест мониторинга бренда {brand}",
        "",
        f"❌ Подделок: {len(fakes)}   ⚠️ Подозрительных: {len(suspicious)}",
        "",
    ]
    for f in (fakes + suspicious)[:10]:
        price = f"{int(f['price'])}₽" if f.get("price") else "цена н/д"
        seller = f.get("seller") or "продавец н/д"
        lines.append(
            f"• [{f['verdict']} {f['confidence']}%] {price}, {seller}\n  {f['url']}"
        )
    return "\n".join(lines)

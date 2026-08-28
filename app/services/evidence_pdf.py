"""Evidence PDF generator (Block D.1).

Builds a legally-usable evidence pack for a case:
- header with case/check ids, brand, URL, generation timestamp,
- side-by-side reference vs suspect comparison,
- full-page screenshot (when captured),
- indicators table + forensic signals (ELA / pHash / EXIF / final score),
- price history of the listing across checks,
- SHA-256 chain-of-custody manifest.
"""

import io
import json
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _safe_loads(raw: Any) -> Any:
    if not raw:
        return None
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return None


def generate_evidence_pdf(
    case: Dict[str, Any],
    check: Dict[str, Any],
    price_history: List[Dict[str, Any]],
    manifest_files: List[Dict[str, Any]],
    screenshot_bytes: Optional[bytes] = None,
    screenshot_meta: Optional[Dict[str, Any]] = None,
) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
    from reportlab.lib.units import mm
    from reportlab.platypus import (
        Image as RLImage,
        PageBreak,
        Paragraph,
        SimpleDocTemplate,
        Spacer,
        Table,
        TableStyle,
    )

    styles = getSampleStyleSheet()
    h2 = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=13, spaceBefore=10)
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9)
    mono = ParagraphStyle("mono", parent=body, fontName="Courier", fontSize=7)

    story = []
    now = datetime.now(timezone.utc).isoformat()
    screenshot_meta = screenshot_meta or {}
    analyzed_at = check.get("checked_at") or "—"
    story.append(Paragraph("FakeDetect — Evidence Package", styles["Title"]))
    meta_rows = [
        ["Case ID", str(case.get("id"))],
        ["Check ID", str(case.get("check_id"))],
        ["Brand", case.get("brand") or "—"],
        ["Marketplace", case.get("marketplace") or "—"],
        ["Listing URL", case.get("url") or "—"],
        ["Seller", case.get("seller") or "—"],
        ["Verdict at detection",
         f"{case.get('verdict')} ({check.get('confidence')}%)"],
        ["Case status", case.get("status")],
        # D-C1: analysis date and screenshot-capture date are kept as two
        # separate rows — a screenshot captured well after analysis must not
        # be presented as if it reflected the page at analysis time.
        ["Дата анализа (UTC)", str(analyzed_at)],
        ["Дата захвата скриншота (UTC)", str(screenshot_meta.get("captured_at") or "—")],
        ["Generated (UTC)", now],
    ]
    t = Table(meta_rows, colWidths=[45 * mm, 120 * mm])
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.4, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story += [t, Spacer(1, 6 * mm)]

    # --- Side-by-side comparison ----------------------------------------------
    from app.services.evidence_store import load_artifact

    ref = load_artifact(case["check_id"], "reference.png")
    sus = load_artifact(case["check_id"], "suspect.png")
    if ref and sus:
        story.append(Paragraph("1. Эталон vs подозрительный товар", h2))
        cells = []
        for blob in (ref, sus):
            try:
                cells.append(RLImage(io.BytesIO(blob), width=70 * mm, height=70 * mm,
                                     preserveAspectRatio=True))
            except Exception:  # noqa: BLE001
                cells.append(Paragraph("(изображение недоступно)", body))
        row = Table([cells], colWidths=[80 * mm, 80 * mm])
        row.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "MIDDLE")]))
        story += [row,
                  Paragraph("Слева — эталон бренда, справа — карточка с маркетплейса.", body)]

    story += [PageBreak(), Paragraph("2. Скриншот карточки", h2)]
    shot_status = screenshot_meta.get("status")
    if screenshot_bytes and shot_status != "captured_late":
        story.append(Paragraph(
            f"Захвачен: {screenshot_meta.get('captured_at') or '—'} "
            f"(на момент проверки).", body))
        try:
            story.append(RLImage(io.BytesIO(screenshot_bytes), width=160 * mm,
                                 height=110 * mm, preserveAspectRatio=True))
        except Exception:  # noqa: BLE001
            story.append(Paragraph("(скриншот не приложен)", body))
    elif screenshot_bytes and shot_status == "captured_late":
        story.append(Paragraph(
            f"⚠ Скриншот захвачен {screenshot_meta.get('captured_at')} — позже "
            f"момента анализа ({analyzed_at}). Может не отражать состояние "
            f"страницы на момент проверки.", body))
        try:
            story.append(RLImage(io.BytesIO(screenshot_bytes), width=160 * mm,
                                 height=110 * mm, preserveAspectRatio=True))
        except Exception:  # noqa: BLE001
            pass
    elif shot_status == "pending":
        story.append(Paragraph(
            "Скриншот ещё не захвачен — попытка захвата продолжается в фоне "
            "(браузер был недоступен на момент анализа). Запросите PDF повторно "
            "позже.", body))
    else:
        story.append(Paragraph(
            "Скриншот недоступен: захват не удался (браузер/сеть недоступны) "
            "в пределах контрольного окна после анализа. Не подменён более "
            "поздним снимком, чтобы не исказить цепочку доказательств.", body))

    # --- Indicators & forensics -------------------------------------------------
    story.append(Paragraph("3. Признаки нарушения и форензик-сигналы", h2))
    ela_score = check.get("ela_score")
    ind_rows = [["Признак", "Оценка", "Статус", "Пояснение"]]
    ind_rows.append([
        "ELA (Error Level Analysis)",
        str(ela_score if ela_score is not None else "—"),
        "FAIL" if check.get("ela_flag") else "ok",
        "Неоднородное сжатие — возможна склейка/ретушь" if check.get("ela_flag")
        else "Равномерное сжатие изображения",
    ])
    phash = check.get("phash")
    if phash:
        ind_rows.append(["pHash изображения", str(phash)[:16] + "…", "INFO",
                         "Перцептивный хэш для сопоставления с другими карточками"])
    for f in (_safe_loads(check.get("exif_flags")) or []):
        ind_rows.append([f.get("factor", "EXIF"), str(f.get("score", "—")),
                         (f.get("status") or "warn").upper(), f.get("detail", "")])
    fs = check.get("final_score")
    ind_rows.append(["Итоговый композитный счёт",
                     f"{fs}/100" if fs is not None else "—", "INFO",
                     "Взвешенная сумма сигналов (формула — в README проекта)"])

    ind_table = Table(ind_rows, colWidths=[55 * mm, 22 * mm, 18 * mm, 75 * mm])
    ind_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story.append(ind_table)

    # --- Price history ------------------------------------------------------------
    story.append(Paragraph("4. История цены товара", h2))
    if price_history:
        price_rows = [["Дата проверки", "Цена, ₽", "Вердикт"]]
        for p in price_history:
            price_rows.append([
                str(p.get("checked_at") or ""),
                f"{int(p['price_suspect'])}" if p.get("price_suspect") else "—",
                str(p.get("verdict") or "—"),
            ])
        pt = Table(price_rows, colWidths=[50 * mm, 30 * mm, 40 * mm])
        pt.setStyle(TableStyle([
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ]))
        story.append(pt)
    else:
        story.append(Paragraph("История цены недоступна (единственная проверка).", body))

    # --- Chain of custody -----------------------------------------------------------
    story.append(Paragraph("5. Цепочка хранения доказательств (SHA-256)", h2))
    cov_rows = [["Файл", "SHA-256", "Сохранён (UTC)"]]
    for f in manifest_files:
        cov_rows.append([f.get("name", "?"), f.get("sha256") or "—",
                         str(f.get("saved_at") or "")])
    cov_table = Table(cov_rows, colWidths=[35 * mm, 85 * mm, 50 * mm])
    cov_table.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 6.5),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.3, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    story += [cov_table, Spacer(1, 4 * mm), Paragraph(
        "Хэши вычислены при сохранении файлов системой FakeDetect (SHA-256) и "
        "позволяют проверить неизменность доказательств на любой момент.", mono)]

    buffer = io.BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4,
                            leftMargin=15 * mm, rightMargin=15 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm)
    doc.build(story)
    return buffer.getvalue()
"""EXIF metadata forensics (Block B.2).

Extracts a safe subset of EXIF and derives red flags:
- no EXIF at all on a "live" seller photo (stripped by editors/scrapers),
- capture date in the future (impossible),
- editing software signatures (informational).
Flags are appended to indicators and stored with the check.
"""

import io
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

SUSPICIOUS_SOFTWARE = ("photoshop", "gimp", "lightroom", "pixelmator", "fotor")


def extract_exif_flags(image_bytes: bytes) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    """Returns (exif_subset_dict, red_flags list of indicator-shaped dicts)."""
    flags: List[Dict[str, str]] = []
    subset: Dict[str, Any] = {}
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(image_bytes))
        exif = img.getexif()
        if not exif or len(exif) == 0:
            return subset, [_missing_exif_flag()]

        software = exif.get(0x0131)          # Software
        date_tag = (
            exif.get(0x0132)                 # DateTime
            or exif.get_ifd(0x8769).get(0x9003)  # Exif IFD: DateTimeOriginal
            if hasattr(exif, "get_ifd")
            else exif.get(0x0132)
        )
        if software:
            subset["software"] = str(software)
        if date_tag:
            subset["datetime"] = str(date_tag)

        if software and any(s in str(software).lower() for s in SUSPICIOUS_SOFTWARE):
            flags.append({
                "factor": "EXIF: след редактора",
                "score": "4",
                "status": "warn",
                "detail": f"Файл сохранён в «{software}» — возможна обработка фото",
            })

        parsed = _parse_datetime(subset.get("datetime"))
        if parsed and parsed > datetime.now():
            flags.append({
                "factor": "EXIF: дата в будущем",
                "score": "7",
                "status": "fail",
                "detail": f"Дата съёмки {parsed} позже текущей — метаданные недостоверны",
            })
    except Exception as e:  # noqa: BLE001
        logging.getLogger(__name__).debug(f"EXIF extraction failed: {e}")
    return subset, flags


def _missing_exif_flag() -> Dict[str, str]:
    return {
        "factor": "EXIF: метаданные отсутствуют",
        "score": "3",
        "status": "warn",
        "detail": "У фото нет EXIF — файл пересохранён или скачан скрейпером; "
                  "сам по себе не признак подделки, но снижает доказательную ценность",
    }


def _parse_datetime(value: Any) -> Optional[datetime]:
    """Parse 'YYYY-MM-DD HH:MM:SS' / 'YYYY:MM:DD HH:MM:SS' EXIF datetime."""
    if not value:
        return None
    raw = str(value).strip().split(".")[0]
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y:%m:%d %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            continue
    return None


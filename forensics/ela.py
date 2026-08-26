"""Error Level Analysis (Block B.2).

Re-saves the image with a known JPEG quality and measures the residual error:
uniformly compressed "native" photos show low uniform error, while spliced /
edited regions exhibit locally elevated error levels. The resulting numeric
score is an independent, explainable signal — never a replacement for the LLM
verdict — and is included in API responses and future evidence packages.

Heuristic calibration: natural photos typically land in ela_score < 15,
images with pasted/edited regions climb above ~25. Thresholds are configurable.
"""

import io
import logging
from typing import Dict, Any

import numpy as np
from PIL import Image

logger = logging.getLogger(__name__)


def compute_ela(
    image_bytes: bytes,
    quality: int = 90,
    flag_threshold: float = 25.0,
) -> Dict[str, Any]:
    """Compute ELA statistics for an image.

    Returns {ela_score: 0..100 float, ela_flag: bool, max_error: float} or
    zeroed result when the image cannot be decoded (never raises).
    """
    try:
        original = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    except Exception as e:  # noqa: BLE001
        logger.warning(f"ELA skipped, image not decodable: {e}")
        return {"ela_score": 0.0, "ela_flag": False, "max_error": 0.0}

    buffer = io.BytesIO()
    original.save(buffer, format="JPEG", quality=quality)
    buffer.seek(0)
    resaved = Image.open(buffer).convert("RGB")

    err = np.asarray(original, dtype=np.float64) - np.asarray(resaved, dtype=np.float64)
    abs_err = np.abs(err)

    rms = float(np.sqrt(np.mean(abs_err ** 2)))       # global compression residue
    max_local = float(np.percentile(abs_err, 99.9))   # localised edit hotspots

    # Normalise into 0..100: RMS dominates, hotspot pushes it up.
    score = min(100.0, round(rms * 6.0 + max(0.0, max_local - 30.0) * 0.5, 1))

    return {
        "ela_score": score,
        "ela_flag": bool(score >= flag_threshold),
        "max_error": round(max_local, 1),
    }

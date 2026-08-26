"""Perceptual hashing (Block B.1).

pHash of every image passing through the system enables:
- instant verdicts for near-duplicate images (hamming distance < threshold),
- reverse image search ("find all checks with similar imagery"),
- deduplication of discovery results (Block C).
"""

import logging
from typing import Optional

from PIL import Image
import imagehash

logger = logging.getLogger(__name__)


def compute_phash(image_bytes: bytes) -> Optional[str]:
    """Return 16-char hex perceptual hash (8x8 pHash) or None on decode error."""
    try:
        img = Image.open(image_from_bytes(image_bytes))
        return str(imagehash.phash(img))
    except Exception as e:  # noqa: BLE001 - forensic layer must never break the flow
        logger.warning(f"pHash computation failed: {e}")
        return None


def image_from_bytes(data: bytes):
    import io

    return io.BytesIO(data)


def hamming_distance(hex_a: str, hex_b: str) -> int:
    """Hamming distance between two hex-encoded hashes; large value on mismatch."""
    try:
        # imagehash returns a numpy integer — cast for JSON serialisation.
        return int(imagehash.hex_to_hash(hex_a) - imagehash.hex_to_hash(hex_b))
    except Exception:  # noqa: BLE001
        # 64 = maximally distant for an 8x8 hash.
        return 64


def similarity_percent(distance: int, bits: int = 64) -> float:
    """Map a hamming distance to a 0..100 similarity score."""
    return round(max(0.0, (1.0 - distance / bits)) * 100.0, 1)

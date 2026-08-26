"""Block B unit tests: pHash, ELA, EXIF, hash storage, composite verdict engine."""

import io

import pytest
from PIL import Image

from forensics.phash import compute_phash


def _png(color=(120, 30, 200), size=64) -> bytes:
    img = Image.new("RGB", (size, size), color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _patched_png(base_color=(120, 30, 200)) -> bytes:
    """Image with a large contrasting patch (simulated splice)."""
    img = Image.new("RGB", (64, 64), base_color)
    for y in range(20, 50):
        for x in range(20, 50):
            img.putpixel((x, y), (250, 240, 10))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


# --- pHash ----------------------------------------------------------------------


@pytest.mark.asyncio
async def test_phash_identical_images_zero_distance(client):
    from database import find_similar_suspect_hash, save_image_hash
    from forensics.phash import hamming_distance, similarity_percent

    data = _png()
    h1 = compute_phash(data)
    h2 = compute_phash(data)
    assert h1 and h2 and hamming_distance(h1, h2) == 0
    assert similarity_percent(0) == 100.0

    await save_image_hash(h1, "suspect", verdict="ПОДДЕЛКА", confidence=80, summary="s")
    match = await find_similar_suspect_hash(h2, max_distance=8)
    assert match is not None
    assert match["verdict"] == "ПОДДЕЛКА"
    assert match["hamming_distance"] == 0


# --- ELA -------------------------------------------------------------------------


def test_ela_flags_edited_image_stronger_than_clean():
    from forensics.ela import compute_ela

    clean = compute_ela(_png(), flag_threshold=25.0)
    edited = compute_ela(_patched_png(), flag_threshold=25.0)
    # A large pasted region must produce a stronger local error signal.
    assert edited["max_error"] > clean["max_error"]
    assert edited["ela_score"] > clean["ela_score"]
    assert edited["ela_flag"] is True or clean["ela_score"] < 25


def test_ela_never_raises_on_garbage():
    from forensics.ela import compute_ela

    result = compute_ela(b"not an image")
    assert result["ela_score"] == 0.0 and result["ela_flag"] is False


# --- EXIF ------------------------------------------------------------------------


def test_exif_missing_on_png():
    from forensics.exif import extract_exif_flags

    subset, flags = extract_exif_flags(_png())
    assert any("отсутствуют" in f["factor"] for f in flags)


def test_exif_editor_software_flagged():
    from PIL import Image
    from forensics.exif import extract_exif_flags

    img = Image.new("RGB", (32, 32))
    exif = img.getexif()
    exif[0x0131] = "Adobe Photoshop 24.0"          # Software tag
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)

    subset, flags = extract_exif_flags(buf.getvalue())
    assert subset.get("software") == "Adobe Photoshop 24.0"
    assert any("редактора" in f["factor"] for f in flags)


# --- Composite verdict engine ----------------------------------------------------


def test_final_score_full_breakdown():
    from core.verdict_engine import compute_final_score

    final, breakdown = compute_final_score(
        llm_confidence=80,
        phash_similarity=60,
        ela_score=10,
        exif_flag_count=1,
        price_ratio=0.5,
        weights={
            "w_llm_confidence": 0.45, "w_phash_similarity": 0.25,
            "w_ela": 0.15, "w_exif": 0.05, "w_price": 0.10,
        },
        price_floor=0.2, price_ceiling=0.8,
    )
    expected = (
        80 * 0.45 + 60 * 0.25 + 90 * 0.15 + 80 * 0.05 + 50 * 0.10
    )  # authenticity values: 80/60/100-10/100-20/(0.5-0.2)/0.6*100=50
    assert final == int(round(expected))
    assert set(breakdown["components"]) == {
        "llm_confidence", "phash_similarity", "ela", "exif", "price_ratio",
    }


def test_final_score_renormalizes_missing_signals():
    from core.verdict_engine import compute_final_score

    final_only_llm, b1 = compute_final_score(llm_confidence=70)
    assert final_only_llm == 70
    final_two, b2 = compute_final_score(llm_confidence=70, ela_score=40)
    # (70*0.45 + 60*0.15) / 0.6 = 67.5 -> 68
    assert abs(final_two - 67.5) <= 1
    assert "phash_similarity" not in b2["components"]

    none_score, _ = compute_final_score(llm_confidence=None)
    assert none_score is None


def test_price_ratio_bounds():
    from core.verdict_engine import compute_final_score

    _, low = compute_final_score(llm_confidence=None, price_ratio=0.05,
                                 price_floor=0.2, price_ceiling=0.8)
    _, high = compute_final_score(llm_confidence=None, price_ratio=2.0,
                                  price_floor=0.2, price_ceiling=0.8)
    assert low["components"]["price_ratio"]["authenticity"] == 0.0
    assert high["components"]["price_ratio"]["authenticity"] == 100.0


def test_confidence_adjustment_clamped():
    from core.verdict_engine import adjust_confidence_with_forensics

    # Forensics contradict LLM: pulled down by at most 15 points.
    assert adjust_confidence_with_forensics("ОРИГИНАЛ", 95, 20) == 80
    # Strong forensic support: up by at most 15 points.
    assert adjust_confidence_with_forensics("ОРИГИНАЛ", 50, 100) == 65
    # No forensic data → unchanged.
    assert adjust_confidence_with_forensics("ОРИГИНАЛ", 77, None) == 77

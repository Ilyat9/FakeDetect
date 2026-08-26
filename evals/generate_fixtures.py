"""Golden dataset fixture generation (Block A.8).

Deterministically creates small PNG pairs (reference vs suspect) whose pixel
difference lands in the three verdict bands used by the offline MockVisionProvider.
Real-provider runs use exactly the same images.
"""

import os

from PIL import Image

DATASET_DIR = os.path.join(os.path.dirname(__file__), "golden_dataset")

SIZE = 64


def _base_image() -> Image.Image:
    img = Image.new("RGB", (SIZE, SIZE))
    for y in range(SIZE):
        for x in range(SIZE):
            img.putpixel((x, y), (x * 4 % 256, y * 4 % 256, (x + y) * 2 % 256))
    return img


def _with_patch(img: Image.Image, box: int) -> Image.Image:
    """Overlay a solid patch in the top-left corner (deterministic edit)."""
    out = img.copy()
    for y in range(box):
        for x in range(box):
            out.putpixel((x, y), (255, 0, 0))
    return out


def ensure_fixtures() -> None:
    """Create dataset images + manifest.json if missing."""
    os.makedirs(DATASET_DIR, exist_ok=True)

    base = _base_image()
    # diff ratios: same=0.0 | 20x20=0.098 | full=1.0
    cases = [
        ("case_original_vs_identical", base, base.copy(), "ОРИГИНАЛ"),
        ("case_slight_edit", base, _with_patch(base, 20), "ПОДОЗРИТЕЛЬНО"),
        ("case_counterfeit_clone", base, Image.new("RGB", (SIZE, SIZE), (10, 200, 30)), "ПОДДЕЛКА"),
        ("case_borderline_edit", base, _with_patch(base, 14), "ПОДОЗРИТЕЛЬНО"),
    ]

    import json

    manifest_path = os.path.join(DATASET_DIR, "manifest.json")
    entries = []
    for name, reference, suspect, expected in cases:
        ref_path = os.path.join(DATASET_DIR, f"{name}_ref.png")
        sus_path = os.path.join(DATASET_DIR, f"{name}_sus.png")
        if not os.path.exists(ref_path):
            reference.save(ref_path)
        if not os.path.exists(sus_path):
            suspect.save(sus_path)
        entries.append({
            "id": name,
            "reference": os.path.relpath(ref_path, DATASET_DIR),
            "suspect": os.path.relpath(sus_path, DATASET_DIR),
            "expected_verdict": expected,
        })

    if not os.path.exists(manifest_path):
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump({"cases": entries}, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    ensure_fixtures()
    print(f"Fixtures ready in {DATASET_DIR}")

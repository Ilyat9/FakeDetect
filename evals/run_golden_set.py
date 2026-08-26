"""Golden-set regression runner (Block A.8).

Mandatory check before merging ANY change to prompts or models:

    python evals/run_golden_set.py --mock          # offline deterministic model
    python evals/run_golden_set.py --provider gemini  # real LLM (needs API key)

Reports accuracy per verdict class and exits non-zero when accuracy drops
below --min-accuracy (default 1.0 for the offline mock).
"""

import argparse
import json
import os
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from evals.generate_fixtures import DATASET_DIR, ensure_fixtures  # noqa: E402

VERDICTS = ("ОРИГИНАЛ", "ПОДОЗРИТЕЛЬНО", "ПОДДЕЛКА")


class MockVisionProvider:
    """Deterministic offline stand-in: classifies by pixel-difference ratio."""

    async def analyze(self, original_bytes: bytes, suspect_bytes: bytes, meta: Dict[str, Any]):
        import io

        from PIL import Image, ImageChops

        ref = Image.open(io.BytesIO(original_bytes)).convert("RGB")
        sus = Image.open(io.BytesIO(suspect_bytes)).convert("RGB")
        total = ref.size[0] * ref.size[1]
        ratio = _changed_pixels(ref, sus) / total
        if ratio < 0.02:
            verdict, confidence = "ОРИГИНАЛ", 92
        elif ratio <= 0.15:
            verdict, confidence = "ПОДОЗРИТЕЛЬНО", 65
        else:
            verdict, confidence = "ПОДДЕЛКА", 85
        return {
            "verdict": verdict,
            "confidence": confidence,
            "summary": f"mock diff_ratio={ratio:.3f}",
            "risk_level": "low" if ratio < 0.02 else "medium" if ratio <= 0.15 else "high",
            "indicators": [],
        }


def _changed_pixels(ref, sus) -> int:
    return sum(
        1
        for (r1, g1, b1), (r2, g2, b2) in zip(ref.getdata(), sus.getdata())
        if abs(r1 - r2) + abs(g1 - g2) + abs(b1 - b2) > 10
    )


async def run(provider_mode: str = "mock") -> Dict[str, Any]:
    ensure_fixtures()
    with open(os.path.join(DATASET_DIR, "manifest.json"), encoding="utf-8") as f:
        manifest = json.load(f)

    provider = None
    if provider_mode == "mock":
        provider = MockVisionProvider()
    else:
        from app.core.config import get_llm_provider, settings

        provider = get_llm_provider(settings.provider)

    results: List[Dict[str, Any]] = []
    for case in manifest["cases"]:
        with open(os.path.join(DATASET_DIR, case["reference"]), "rb") as f:
            ref_bytes = f.read()
        with open(os.path.join(DATASET_DIR, case["suspect"]), "rb") as f:
            sus_bytes = f.read()

        if provider_mode == "mock":
            raw = await provider.analyze(ref_bytes, sus_bytes, {})
            verdict = raw["verdict"]
        else:
            # Real path goes through strict validation (A.4).
            from app.core.llm_gateway import prompt_fingerprint, validated_provider_call

            result = await validated_provider_call(provider, ref_bytes, sus_bytes, {}, "golden")
            verdict = result.verdict

        ok = verdict == case["expected_verdict"]
        results.append({
            "id": case["id"],
            "expected": case["expected_verdict"],
            "got": verdict,
            "ok": ok,
        })

    accuracy = sum(1 for r in results if r["ok"]) / len(results) if results else 0.0
    per_class: Dict[str, Dict[str, int]] = {
        v: {"total": 0, "correct": 0} for v in VERDICTS
    }
    for r in results:
        per_class.setdefault(r["expected"], {"total": 0, "correct": 0})
        per_class[r["expected"]]["total"] += 1
        per_class[r["expected"]]["correct"] += int(r["ok"])

    return {"accuracy": accuracy, "per_class": per_class, "results": results}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the FakeDetect golden set")
    parser.add_argument("--mock", action="store_true", help="offline deterministic mode")
    parser.add_argument(
        "--provider",
        default=None,
        choices=["gemini", "grok"],
        help="real provider to evaluate (requires configured API key)",
    )
    parser.add_argument("--min-accuracy", type=float, default=None)
    args = parser.parse_args()

    mode = "mock" if args.mock or not args.provider else args.provider
    min_accuracy = args.min_accuracy
    if min_accuracy is None:
        min_accuracy = 1.0 if mode == "mock" else 0.75

    import asyncio

    report = asyncio.run(run(mode))

    print(f"\n=== Golden set report ({mode}) ===")
    print(f"accuracy: {report['accuracy']:.2%}")
    for cls, stats in report["per_class"].items():
        if stats["total"]:
            print(f"  {cls}: {stats['correct']}/{stats['total']}")
    for r in report["results"]:
        mark = "PASS" if r["ok"] else "FAIL"
        print(f"  [{mark}] {r['id']}: expected={r['expected']} got={r['got']}")

    failed = report["accuracy"] < min_accuracy
    print(f"\nthreshold: {min_accuracy:.0%} -> {'FAILED' if failed else 'PASSED'}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())

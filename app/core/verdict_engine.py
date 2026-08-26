"""Explainable composite verdict engine (Block B.4).

final_score = Σ (w_i × s_i) / Σ w_i   over the available signals, where every
signal s_i is normalised to 0..100 "authenticity" (higher = more likely
original):

- llm_confidence : LLM verdict confidence, as-is;
- phash_similarity : similarity of the suspect image to the reference (0..100);
- ela_authenticity : 100 − ela_score (higher compression residue → less authentic);
- exif_authenticity: 100 − 20 × number_of_exif_red_flags (floored at 0);
- price_authenticity : price ratio mapped linearly from floor→0 to ceiling→100.

Missing signals are excluded and the remaining weights re-normalised — the
score stays comparable across cases with different available data. The full
per-component breakdown is returned so the API can explain "why exactly 72".
"""

from typing import Any, Dict, Optional, Tuple


def compute_final_score(
    llm_confidence: Optional[float],
    phash_similarity: Optional[float] = None,
    ela_score: Optional[float] = None,
    exif_flag_count: int = 0,
    price_ratio: Optional[float] = None,
    weights: Optional[Dict[str, float]] = None,
    price_floor: float = 0.2,
    price_ceiling: float = 0.8,
) -> Tuple[Optional[int], Dict[str, Any]]:
    """Return (final_score 0..100 or None, breakdown dict)."""
    weights = weights or {}

    components: Dict[str, Dict[str, Any]] = {}

    def add(key: str, weight: float, raw: Any, authenticity: float):
        components[key] = {
            "raw": raw,
            "weight": weight,
            "authenticity": round(authenticity, 1),
        }

    if llm_confidence is not None:
        add("llm_confidence", weights.get("w_llm_confidence", 0.45), llm_confidence,
            float(llm_confidence))
    if phash_similarity is not None:
        add("phash_similarity", weights.get("w_phash_similarity", 0.25),
            phash_similarity, float(phash_similarity))
    if ela_score is not None:
        add("ela", weights.get("w_ela", 0.15), ela_score, 100.0 - float(ela_score))
    if exif_flag_count:
        add("exif", weights.get("w_exif", 0.05), exif_flag_count,
            max(0.0, 100.0 - 20.0 * exif_flag_count))
    if price_ratio is not None and price_ratio > 0:
        ratio = min(1.0, float(price_ratio))
        span = max(price_ceiling - price_floor, 1e-6)
        authenticity = max(0.0, min(100.0, (ratio - price_floor) / span * 100.0))
        add("price_ratio", weights.get("w_price", 0.10), round(ratio, 3), authenticity)

    scored = {k: v for k, v in components.items() if v["weight"] > 0}
    total_weight = sum(v["weight"] for v in scored.values())
    if not scored or total_weight <= 0:
        return None, {"components": {}, "formula": "no scored signals"}

    final = sum(v["authenticity"] * v["weight"] for v in scored.values()) / total_weight

    # Verdict consistency guardrail: LLM remains authoritative for the label,
    # but a strong forensic contradiction drags confidence down.
    return int(round(final)), {
        "components": components,
        "total_weight": round(total_weight, 3),
        "formula": "Σ(w·s)/Σw over available signals",
    }


def adjust_confidence_with_forensics(
    llm_verdict: str,
    llm_confidence: int,
    final_score: Optional[int],
) -> int:
    """Nudge reported confidence toward the forensic composite when they diverge.

    The LLM keeps the verdict label; forensics can only modulate expressed
    certainty (±15 points max). Keeps behaviour predictable and auditable.
    """
    if final_score is None:
        return llm_confidence
    delta = (final_score - llm_confidence) * 0.5
    delta = max(-15.0, min(15.0, delta))
    return int(max(0, min(100, round(llm_confidence + delta))))

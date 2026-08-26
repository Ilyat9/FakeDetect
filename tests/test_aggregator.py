"""Aggregator verdict rules unit tests."""

from aggregator import (
    FAKE_IN_REVIEWS_CONFIDENCE,
    SUSPICIOUS_RATIO_THRESHOLD,
    ImageAggregator,
    ImageAnalysisResult,
)


def _r(verdict, confidence=80):
    return ImageAnalysisResult(
        image_type="card", index=0, verdict=verdict, confidence=confidence,
        summary="", risk_level="low", indicators=[],
    )


def test_empty_results_unknown():
    verdict, confidence, risk, summary = ImageAggregator()._determine_verdict([], [])
    assert verdict == "UNKNOWN" and confidence == 0


def test_any_fake_in_reviews_means_fake():
    card = [_r("ОРИГИНАЛ")]
    review = [_r("ПОДДЕЛКА")]
    verdict, confidence, _, _ = ImageAggregator()._determine_verdict(card, review)
    assert verdict == "ПОДДЕЛКА"
    assert confidence == FAKE_IN_REVIEWS_CONFIDENCE


def test_high_suspicious_ratio_is_suspicious():
    results = [_r("ОРИГИНАЛ"), _r("ПОДОЗРИТЕЛЬНО"), _r("ПОДОЗРИТЕЛЬНО"), _r("ПОДОЗРИТЕЛЬНО")]
    verdict, _, _, _ = ImageAggregator()._determine_verdict(results, [])
    assert verdict == "ПОДОЗРИТЕЛЬНО"


def test_all_originals():
    results = [_r("ОРИГИНАЛ") for _ in range(5)]
    verdict, confidence, risk, _ = ImageAggregator()._determine_verdict(results, [])
    assert verdict == "ОРИГИНАЛ" and risk == "low"


def test_fake_in_cards_without_review_fakes():
    results = [_r("ОРИГИНАЛ"), _r("ПОДДЕЛКА")]
    verdict, _, _, _ = ImageAggregator()._determine_verdict(results, [])
    assert verdict == "ПОДДЕЛКА"


def test_threshold_constant_value():
    assert SUSPICIOUS_RATIO_THRESHOLD == 0.30

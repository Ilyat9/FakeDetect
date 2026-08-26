"""Block A.8: golden dataset regression runner must pass in offline mode."""

import io
import sys

import pytest


def test_golden_set_mock_mode_passes():
    import asyncio
    import sys

    sys.path.insert(0, ".")
    from evals.run_golden_set import run

    report = asyncio.run(run("mock"))
    assert report["accuracy"] == 1.0, report["results"]
    assert set(report["per_class"]) >= {"ОРИГИНАЛ", "ПОДДЕЛКА", "ПОДОЗРИТЕЛЬНО"}


def test_prompt_fingerprint_stable():
    """A.8: prompt fingerprint must be deterministic for identical meta."""
    from core.llm_gateway import prompt_fingerprint

    a = prompt_fingerprint({"brand": "X", "marketplace": "WB"})
    b = prompt_fingerprint({"brand": "X", "marketplace": "WB"})
    assert a == b
    assert a["prompt_version"]
    assert len(a["prompt_hash"]) == 64

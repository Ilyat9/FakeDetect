"""Strict contracts for LLM analysis output (Block A.4).

Every raw JSON payload coming back from a vision provider MUST be validated
through ``AnalysisResult`` before it is trusted, persisted or shown to users.
Validation failure triggers exactly one corrective retry (see core/llm_gateway);
a second failure degrades gracefully to a "manual review" verdict instead of a 500.
"""

from enum import Enum
from typing import Any, Dict, List

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Verdict(str, Enum):
    ORIGINAL = "ОРИГИНАЛ"
    FAKE = "ПОДДЕЛКА"
    SUSPICIOUS = "ПОДОЗРИТЕЛЬНО"
    MANUAL_REVIEW = "ТРЕБУЕТ РУЧНОЙ ПРОВЕРКИ"


class RiskLevel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    UNKNOWN = "unknown"


_VERDICT_ALIASES = {
    "оригинал": Verdict.ORIGINAL,
    "original": Verdict.ORIGINAL,
    "подделка": Verdict.FAKE,
    "fake": Verdict.FAKE,
    "подозрительно": Verdict.SUSPICIOUS,
    "suspicious": Verdict.SUSPICIOUS,
    "требует ручной проверки": Verdict.MANUAL_REVIEW,
    "manual review": Verdict.MANUAL_REVIEW,
}


class Indicator(BaseModel):
    model_config = ConfigDict(extra="allow")

    factor: str
    score: int = Field(ge=1, le=10)
    status: str
    detail: str = ""

    @field_validator("factor")
    @classmethod
    def _factor_not_empty(cls, v: str) -> str:
        v = (v or "").strip()
        if not v:
            raise ValueError("indicator.factor must not be empty")
        return v

    @field_validator("status")
    @classmethod
    def _status_allowed(cls, v: str) -> str:
        v = (v or "").strip().lower()
        if v not in ("ok", "warn", "fail"):
            raise ValueError(f"indicator.status must be ok|warn|fail, got '{v}'")
        return v


class AnalysisResult(BaseModel):
    """Validated single-image analysis verdict."""

    # use_enum_values: model_dump() emits plain strings, keeping the historical
    # JSON shape consumed by the frontend and saved_check().
    model_config = ConfigDict(extra="allow", use_enum_values=True)

    verdict: Verdict
    confidence: int = Field(ge=0, le=100)
    summary: str = ""
    risk_level: RiskLevel = RiskLevel.UNKNOWN
    indicators: List[Indicator] = Field(default_factory=list)
    recommendation: str = ""

    @field_validator("verdict", mode="before")
    @classmethod
    def _normalize_verdict(cls, v: Any) -> Any:
        if isinstance(v, str):
            alias = _VERDICT_ALIASES.get(v.strip().lower())
            if alias is not None:
                return alias.value
        return v

    @field_validator("risk_level", mode="before")
    @classmethod
    def _normalize_risk(cls, v: Any) -> Any:
        if isinstance(v, str):
            v = v.strip().lower()
            if v in ("unknown", "", "none", "null"):
                return RiskLevel.UNKNOWN.value
        return v

    @field_validator("summary", "recommendation")
    @classmethod
    def _strings_coerced(cls, v: Any) -> str:
        return "" if v is None else str(v)

    @classmethod
    def manual_review(cls, reason: str) -> "AnalysisResult":
        """Graceful-degradation verdict used when models fail us."""
        return cls(
            verdict=Verdict.MANUAL_REVIEW,
            confidence=0,
            summary=reason,
            risk_level=RiskLevel.UNKNOWN,
            indicators=[
                Indicator(
                    factor="Автоматический вердикт недоступен",
                    score=1,
                    status="warn",
                    detail=reason,
                )
            ],
            recommendation="Передайте кейс эксперту на ручную проверку",
        )

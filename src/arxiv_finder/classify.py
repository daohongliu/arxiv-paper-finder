from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, ValidationError, field_validator

CATEGORIES = ("alignment", "robustness", "monitoring", "systemic_safety")
SUBCATEGORIES = ("evaluations", "interpretability", "other")


class ScreenResult(BaseModel):
    is_frontier_ai_safety: bool
    confidence: float = Field(ge=0.0, le=1.0)
    category: str | None = None
    subcategory: str | None = None
    rationale: str = ""

    @field_validator("subcategory")
    @classmethod
    def _validate_pair(cls, v: str | None, info: Any) -> str | None:
        if v is not None and v not in SUBCATEGORIES:
            raise ValueError(f"subcategory must be one of {SUBCATEGORIES}")
        return v

    @field_validator("category")
    @classmethod
    def _validate_category(cls, v: str | None) -> str | None:
        if v is not None and v not in CATEGORIES:
            raise ValueError(f"category must be one of {CATEGORIES}")
        return v


def parse_screen_result(raw: dict[str, Any]) -> ScreenResult:
    if raw.get("category") in ("", "none", "None"):
        raw["category"] = None
    if raw.get("subcategory") in ("", "none", "None"):
        raw["subcategory"] = None
    try:
        conf = float(raw.get("confidence", 0.5))
    except (TypeError, ValueError):
        conf = 0.5
    raw["confidence"] = max(0.0, min(1.0, conf))
    if raw.get("category") == "monitoring" and raw.get("subcategory") is None:
        raw["subcategory"] = "other"
    return ScreenResult.model_validate(raw)


def decide(
    result: ScreenResult, escalate_below: float, review_below: float, escalated: bool
) -> tuple[str, str]:
    if result.confidence < (review_below if escalated else escalate_below):
        return ("needs_review", "escalate" if not escalated else "human_review")
    if result.is_frontier_ai_safety:
        return ("screened_included", "included")
    return ("screened_excluded", "excluded")


def validate_or_raise(raw: dict[str, Any]) -> ScreenResult:
    try:
        return parse_screen_result(raw)
    except ValidationError as exc:
        raise ValueError(f"invalid screen result: {exc}") from exc

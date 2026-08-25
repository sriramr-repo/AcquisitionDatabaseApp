"""Discretionary asset-fit component for the redesigned Gold layer.

This component is intentionally independent from eligibility and does not
write Gold outputs or calculate the final acquisition score.
"""

import json
import math
from typing import Any, Optional

import pandas as pd


MAX_SCORE = 18.0
HIGH_SHARE_THRESHOLD = 0.90
PREDOMINANT_SHARE_THRESHOLD = 0.75
LOW_SHARE_THRESHOLD = 0.50
MEANINGFUL_DISCRETIONARY_AUM = 25_000_000.0


def _numeric(value: Any) -> Optional[float]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def calculate_discretionary_fit(
    discretionary_aum: Any,
    total_aum: Any,
) -> dict[str, Any]:
    """Calculate discretionary share, score, and reason codes for one firm.

    Missing inputs produce an unavailable (None) share and score. A negative
    discretionary amount, a non-positive total AUM, or discretionary AUM
    greater than total AUM is treated as an invalid source relationship: the
    score is None and ``INVALID_DISCRETIONARY_AUM_RELATIONSHIP`` is emitted.
    """
    discretionary = _numeric(discretionary_aum)
    total = _numeric(total_aum)
    if discretionary is None or total is None:
        return {
            "discretionary_share": None,
            "discretionary_fit_score": None,
            "invalid_discretionary_aum_relationship": False,
            "reason_codes": ["MISSING_DISCRETIONARY_DATA"],
        }

    if discretionary < 0 or total <= 0 or discretionary > total:
        return {
            "discretionary_share": None,
            "discretionary_fit_score": None,
            "invalid_discretionary_aum_relationship": True,
            "reason_codes": ["INVALID_DISCRETIONARY_AUM_RELATIONSHIP"],
        }

    share = min(max(discretionary / total, 0.0), 1.0)
    score = 15.0 * share + 3.0 * min(max(discretionary / MEANINGFUL_DISCRETIONARY_AUM, 0.0), 1.0)
    reasons: list[str] = []
    if share >= HIGH_SHARE_THRESHOLD:
        reasons.append("HIGH_DISCRETIONARY_SHARE")
    if share >= PREDOMINANT_SHARE_THRESHOLD:
        reasons.append("PREDOMINANTLY_DISCRETIONARY")
    if share < LOW_SHARE_THRESHOLD:
        reasons.append("LOW_DISCRETIONARY_SHARE")
    if discretionary >= MEANINGFUL_DISCRETIONARY_AUM:
        reasons.append("MEANINGFUL_DISCRETIONARY_AUM")
    return {
        "discretionary_share": round(share, 10),
        "discretionary_fit_score": round(min(score, MAX_SCORE), 10),
        "invalid_discretionary_aum_relationship": False,
        "reason_codes": reasons,
    }


def evaluate_discretionary_fit(firms: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of ``firms`` with only discretionary component fields."""
    result = firms.copy()
    values = result.apply(
        lambda row: calculate_discretionary_fit(
            row.get("discretionary_aum"), row.get("total_aum")
        ),
        axis=1,
        result_type="expand",
    )
    result["discretionary_share"] = values["discretionary_share"]
    result["discretionary_fit_score"] = values["discretionary_fit_score"]
    result["invalid_discretionary_aum_relationship"] = values[
        "invalid_discretionary_aum_relationship"
    ]
    result["discretionary_reason_codes"] = values["reason_codes"].map(
        lambda codes: json.dumps(codes, separators=(",", ":"))
    )
    return result

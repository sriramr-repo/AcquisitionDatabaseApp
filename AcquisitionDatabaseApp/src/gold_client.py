"""Client asset-fit component for the redesigned Gold layer.

This module is independent from eligibility and other scoring components. It
does not write Gold outputs or calculate the final acquisition score.
"""

import json
import math
from typing import Any, Optional

import pandas as pd


MAX_SCORE = 18.0
INDIVIDUAL_FOCUSED_THRESHOLD = 0.50
HNW_INDIVIDUAL_FOCUSED_THRESHOLD = 0.75
HIGH_HNW_SHARE_THRESHOLD = 0.50


def _numeric(value: Any) -> Optional[float]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def calculate_client_fit(
    individual_hnw_client_aum: Any,
    hnw_client_aum: Any,
    total_aum: Any,
) -> dict[str, Any]:
    """Calculate client shares, score, validity, and reason codes for one firm."""
    individual_hnw = _numeric(individual_hnw_client_aum)
    hnw = _numeric(hnw_client_aum)
    total = _numeric(total_aum)

    if individual_hnw is None or hnw is None or total is None:
        return {
            "individual_hnw_share": None if individual_hnw is None or total is None else individual_hnw / total if total > 0 else None,
            "hnw_share": None if hnw is None or total is None else hnw / total if total > 0 else None,
            "client_fit_score": None,
            "invalid_client_aum_relationship": False,
            "reason_codes": ["MISSING_CLIENT_MIX_DATA"],
        }

    if (
        total <= 0
        or individual_hnw < 0
        or hnw < 0
        or individual_hnw > total
        or hnw > total
        or hnw > individual_hnw
    ):
        return {
            "individual_hnw_share": None,
            "hnw_share": None,
            "client_fit_score": None,
            "invalid_client_aum_relationship": True,
            "reason_codes": ["INVALID_CLIENT_AUM_RELATIONSHIP"],
        }

    individual_hnw_share = min(max(individual_hnw / total, 0.0), 1.0)
    hnw_share = min(max(hnw / total, 0.0), 1.0)
    score = 12.0 * individual_hnw_share + 6.0 * hnw_share
    reasons: list[str] = []
    if individual_hnw_share >= HNW_INDIVIDUAL_FOCUSED_THRESHOLD:
        reasons.append("HNW_INDIVIDUAL_FOCUSED")
    elif individual_hnw_share >= INDIVIDUAL_FOCUSED_THRESHOLD:
        reasons.append("INDIVIDUAL_CLIENT_FOCUSED")
    else:
        reasons.append("LOW_INDIVIDUAL_HNW_SHARE")
    if hnw_share >= HIGH_HNW_SHARE_THRESHOLD:
        reasons.append("HIGH_HNW_AUM_SHARE")

    return {
        "individual_hnw_share": round(individual_hnw_share, 10),
        "hnw_share": round(hnw_share, 10),
        "client_fit_score": round(min(score, MAX_SCORE), 10),
        "invalid_client_aum_relationship": False,
        "reason_codes": reasons,
    }


def evaluate_client_fit(firms: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of ``firms`` with only client-fit component fields."""
    result = firms.copy()
    values = result.apply(
        lambda row: calculate_client_fit(
            row.get("individual_hnw_client_aum"),
            row.get("hnw_client_aum"),
            row.get("total_aum"),
        ),
        axis=1,
        result_type="expand",
    )
    result["individual_hnw_share"] = values["individual_hnw_share"]
    result["hnw_share"] = values["hnw_share"]
    result["client_fit_score"] = values["client_fit_score"]
    result["invalid_client_aum_relationship"] = values[
        "invalid_client_aum_relationship"
    ]
    result["client_fit_reason_codes"] = values["reason_codes"].map(
        lambda codes: json.dumps(codes, separators=(",", ":"))
    )
    return result

"""Deterministic sourcing-priority segmentation for the Gold V1 outputs."""

import json
from typing import Any

import pandas as pd


PRIORITY_A_THRESHOLD = 92.5
PRIORITY_B_THRESHOLD = 75.0


def _missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def assign_priority(
    acquisition_score: Any,
    *,
    eligibility_status: str,
    priority_readiness: str,
    review_required: bool,
    hard_exclusion_reason: Any = None,
) -> dict[str, Any]:
    """Assign one of the four V1 priority categories."""
    excluded = eligibility_status == "EXCLUDED" or not _missing(hard_exclusion_reason)
    score = None if _missing(acquisition_score) else float(acquisition_score)
    reasons: list[str] = []

    if excluded:
        category = "EXCLUDED"
        if not _missing(hard_exclusion_reason):
            reasons.append(str(hard_exclusion_reason))
        else:
            reasons.append("EXCLUDED_ELIGIBILITY")
    elif score is None:
        category = "PRIORITY_C"
        reasons.append("MISSING_ACQUISITION_SCORE")
    elif (
        score >= PRIORITY_A_THRESHOLD
        and priority_readiness == "PRIORITY_READY"
        and not review_required
    ):
        category = "PRIORITY_A"
        reasons.append("HIGH_SCORE_PRIORITY_READY")
    elif score >= PRIORITY_B_THRESHOLD:
        category = "PRIORITY_B"
        if score >= PRIORITY_A_THRESHOLD:
            reasons.append("HIGH_SCORE_REVIEW_REQUIRED")
        else:
            reasons.extend(["STRONG_SCORE", "BELOW_PRIORITY_A_THRESHOLD"])
    else:
        category = "PRIORITY_C"
        reasons.append("LOWER_STRUCTURED_FIT")

    return {
        "priority_category": category,
        "priority_reason_codes": json.dumps(reasons, separators=(",", ":")),
    }


def evaluate_priorities(firms: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with priority fields while preserving review overlays."""
    result = firms.copy()
    values = result.apply(
        lambda row: assign_priority(
            row.get("acquisition_score"),
            eligibility_status=row.get("eligibility_status", "ELIGIBLE"),
            priority_readiness=row.get("priority_readiness", "REVIEW_BEFORE_PRIORITY"),
            review_required=bool(row.get("review_required", False)),
            hard_exclusion_reason=row.get("hard_exclusion_reason"),
        ),
        axis=1,
        result_type="expand",
    )
    result["priority_category"] = values["priority_category"]
    result["priority_reason_codes"] = values["priority_reason_codes"]
    return result

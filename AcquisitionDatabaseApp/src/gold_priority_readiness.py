"""Readiness gate for future high-priority classification.

This module deliberately does not assign Priority A/B/C or alter the numeric
acquisition score.
"""

import json
from typing import Any

import pandas as pd


MATERIAL_COMPONENTS = (
    "aum_fit_score",
    "discretionary_fit_score",
    "client_fit_score",
    "account_practice_fit_score",
    "regulatory_quality_score",
)
SUPPORTING_COMPONENTS = (
    "practice_complexity_score",
    "advisory_model_fit_score",
)
CRITICAL_INVALID_FLAGS = (
    "invalid_discretionary_aum_relationship",
    "invalid_client_aum_relationship",
    "invalid_account_relationship",
)


def _missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def calculate_priority_readiness(row: Any) -> dict[str, Any]:
    """Evaluate readiness for one aggregate-scored firm."""
    missing_material = [field for field in MATERIAL_COMPONENTS if _missing(row.get(field))]
    hard_excluded = row.get("eligibility_status") == "EXCLUDED" or not _missing(row.get("hard_exclusion_reason"))
    completeness = row.get("score_completeness_pct")
    try:
        completeness_value = float(completeness)
    except (TypeError, ValueError):
        completeness_value = None
    insufficient_completeness = completeness_value is None or completeness_value < 90.0
    regulatory_review = bool(row.get("regulatory_review_flag", False))
    registration_review = bool(
        row.get("status_review_required", False)
        or (row.get("eligibility_status") == "REVIEW_REQUIRED" and not regulatory_review)
    )
    invalid_material = any(bool(row.get(field, False)) for field in CRITICAL_INVALID_FLAGS)

    reasons: list[str] = []
    if "client_fit_score" in missing_material:
        reasons.append("MISSING_MATERIAL_CLIENT_DATA")
    if any(field != "client_fit_score" for field in missing_material):
        reasons.append("MISSING_MATERIAL_DATA")
    if insufficient_completeness:
        reasons.append("INSUFFICIENT_PRIORITY_COMPLETENESS")
    if regulatory_review:
        reasons.append("REGULATORY_REVIEW_REQUIRED")
    if registration_review:
        reasons.append("REGISTRATION_REVIEW_REQUIRED")
    if invalid_material:
        reasons.append("INVALID_MATERIAL_SCORING_DATA")
    if hard_excluded:
        reasons.append("HARD_EXCLUSION")

    if hard_excluded:
        readiness = "NOT_PRIORITY_ELIGIBLE"
    elif reasons:
        readiness = "REVIEW_BEFORE_PRIORITY"
    else:
        readiness = "PRIORITY_READY"
        reasons.append("PRIORITY_DATA_COMPLETE")

    return {
        "priority_readiness": readiness,
        "priority_ready": readiness == "PRIORITY_READY",
        "missing_material_components": json.dumps(missing_material, separators=(",", ":")),
        "priority_readiness_reason_codes": json.dumps(reasons, separators=(",", ":")),
    }


def evaluate_priority_readiness(firms: pd.DataFrame) -> pd.DataFrame:
    """Return a copy with readiness fields; never changes scoring columns."""
    result = firms.copy()
    values = result.apply(calculate_priority_readiness, axis=1, result_type="expand")
    for field in (
        "priority_readiness",
        "priority_ready",
        "missing_material_components",
        "priority_readiness_reason_codes",
    ):
        result[field] = values[field]
    return result

"""Explainable V1 aggregation of the seven Gold scoring components."""

import json
import math
from typing import Any, Mapping, Optional

import pandas as pd

from src.gold_advisory_model import evaluate_advisory_model_fit
from src.gold_account_practice import evaluate_account_practice_fit
from src.gold_client import evaluate_client_fit
from src.gold_discretionary import evaluate_discretionary_fit
from src.gold_eligibility import SCORE_VERSION, evaluate_eligibility
from src.gold_practice_complexity import evaluate_practice_complexity
from src.gold_regulatory import evaluate_regulatory_quality


COMPONENT_WEIGHTS = {
    "aum_fit_score": 20,
    "discretionary_fit_score": 18,
    "client_fit_score": 18,
    "account_practice_fit_score": 14,
    "practice_complexity_score": 10,
    "advisory_model_fit_score": 10,
    "regulatory_quality_score": 10,
}
TOTAL_WEIGHT = sum(COMPONENT_WEIGHTS.values())

COMPONENT_REASON_COLUMNS = (
    "reason_codes",
    "discretionary_reason_codes",
    "client_fit_reason_codes",
    "account_practice_reason_codes",
    "practice_complexity_reason_codes",
    "advisory_model_reason_codes",
    "regulatory_quality_reason_codes",
)


def _missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _as_reason_list(value: Any) -> list[str]:
    if _missing(value):
        return []
    if isinstance(value, (list, tuple)):
        return [str(item) for item in value]
    try:
        parsed = json.loads(str(value))
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return []


def calculate_acquisition_score(
    component_scores: Mapping[str, Any],
    *,
    eligibility_status: str = "ELIGIBLE",
    hard_exclusion_reason: Optional[str] = None,
    eligibility_review_required: bool = False,
    regulatory_review_flag: bool = False,
    reason_lists: Optional[Mapping[str, Any]] = None,
) -> dict[str, Any]:
    """Aggregate component scores with observed-weight normalization."""
    available: dict[str, float] = {}
    missing_components: list[str] = []
    for field in COMPONENT_WEIGHTS:
        value = component_scores.get(field)
        if _missing(value):
            missing_components.append(field)
            continue
        try:
            number = float(value)
        except (TypeError, ValueError):
            missing_components.append(field)
            continue
        if not math.isfinite(number):
            missing_components.append(field)
        else:
            available[field] = number

    available_weight = sum(COMPONENT_WEIGHTS[field] for field in available)
    missing_weight = TOTAL_WEIGHT - available_weight
    completeness = available_weight / TOTAL_WEIGHT * 100
    hard_excluded = eligibility_status == "EXCLUDED" or hard_exclusion_reason is not None
    score = None
    if not hard_excluded and available_weight:
        score = round(sum(available.values()) / available_weight * TOTAL_WEIGHT, 10)
        score = min(max(score, 0.0), 100.0)

    completeness_review = missing_weight > 30
    review_required = False if hard_excluded else bool(
        eligibility_review_required or regulatory_review_flag or completeness_review
    )

    reasons: list[str] = []
    for value in (reason_lists or {}).values():
        for reason in _as_reason_list(value):
            if reason not in reasons:
                reasons.append(reason)
    if completeness_review and "INCOMPLETE_SCORE_REVIEW" not in reasons:
        reasons.append("INCOMPLETE_SCORE_REVIEW")

    return {
        "score_version": SCORE_VERSION,
        "eligibility_status": eligibility_status,
        "review_required": review_required,
        "hard_exclusion_reason": hard_exclusion_reason,
        "acquisition_score": score,
        "available_component_weight": available_weight,
        "missing_component_weight": missing_weight,
        "score_completeness_pct": completeness,
        "missing_score_components": json.dumps(missing_components, separators=(",", ":")),
        "score_completeness_review_flag": completeness_review,
        "regulatory_review_flag": bool(regulatory_review_flag),
        "reason_codes": json.dumps(reasons, separators=(",", ":")),
    }


def evaluate_acquisition_scores(
    firms: pd.DataFrame,
    *,
    run_components: bool = False,
) -> pd.DataFrame:
    """Aggregate scores in memory, optionally running the seven V1 evaluators."""
    result = firms.copy()
    if run_components:
        result = evaluate_eligibility(result)
        result = evaluate_discretionary_fit(result)
        result = evaluate_client_fit(result)
        result = evaluate_account_practice_fit(result)
        result = evaluate_practice_complexity(result)
        result = evaluate_advisory_model_fit(result)
        result = evaluate_regulatory_quality(result)

    if "eligibility_status" not in result.columns:
        result["eligibility_status"] = "ELIGIBLE"
    if "hard_exclusion_reason" not in result.columns:
        result["hard_exclusion_reason"] = None
    if "review_required" not in result.columns:
        result["review_required"] = False
    if "regulatory_review_flag" not in result.columns:
        result["regulatory_review_flag"] = False

    if "reason_codes" in result.columns:
        result["eligibility_reason_codes"] = result["reason_codes"]
    else:
        result["eligibility_reason_codes"] = json.dumps([])

    aggregates = result.apply(
        lambda row: calculate_acquisition_score(
            {field: row.get(field) for field in COMPONENT_WEIGHTS},
            eligibility_status=row.get("eligibility_status", "ELIGIBLE"),
            hard_exclusion_reason=row.get("hard_exclusion_reason"),
            eligibility_review_required=bool(row.get("review_required", False)),
            regulatory_review_flag=bool(row.get("regulatory_review_flag", False)),
            reason_lists={field: row.get(field) for field in COMPONENT_REASON_COLUMNS},
        ),
        axis=1,
        result_type="expand",
    )
    for field in aggregates.columns:
        result[field] = aggregates[field]
    return result

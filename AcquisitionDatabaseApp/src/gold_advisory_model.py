"""Advisory-model compatibility component for the redesigned Gold layer."""

import json
from typing import Any, Optional

import pandas as pd


MAX_SCORE = 10.0
SCORING_FIELDS = (
    "advises_individuals_or_small_businesses",
    "provides_financial_planning",
    "advises_pooled_investment_vehicles",
    "advises_institutional_clients",
    "provides_pension_consulting",
    "selects_other_advisers",
)


def _boolean(value: Any) -> Optional[bool]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().upper()
        if normalized == "Y":
            return True
        if normalized == "N":
            return False
    return None


def calculate_advisory_model_fit(
    advises_individuals_or_small_businesses: Any,
    provides_financial_planning: Any,
    advises_pooled_investment_vehicles: Any,
    advises_institutional_clients: Any,
    provides_pension_consulting: Any,
    selects_other_advisers: Any,
) -> dict[str, Any]:
    """Calculate the approved Item 5.G advisory-model score."""
    values = {
        name: _boolean(value)
        for name, value in zip(
            SCORING_FIELDS,
            (
                advises_individuals_or_small_businesses,
                provides_financial_planning,
                advises_pooled_investment_vehicles,
                advises_institutional_clients,
                provides_pension_consulting,
                selects_other_advisers,
            ),
        )
    }
    missing = [name for name, value in values.items() if value is None]
    individual_points = 6.0 if values[SCORING_FIELDS[0]] is True else 0.0
    planning_points = 2.0 if values[SCORING_FIELDS[1]] is True else 0.0
    pooled_penalty = 1.0 if values[SCORING_FIELDS[2]] is True else 0.0
    institutional_penalty = 1.0 if values[SCORING_FIELDS[3]] is True else 0.0
    pension_penalty = 1.0 if values[SCORING_FIELDS[4]] is True else 0.0
    other_adviser_penalty = 1.0 if values[SCORING_FIELDS[5]] is True else 0.0

    reasons: list[str] = []
    if missing:
        reasons.append("MISSING_ADVISORY_MODEL_DATA")
    if values[SCORING_FIELDS[0]] is True:
        reasons.append("INDIVIDUAL_SMALL_BUSINESS_MODEL")
    if values[SCORING_FIELDS[1]] is True:
        reasons.append("FINANCIAL_PLANNING_MODEL")
    if values[SCORING_FIELDS[2]] is True:
        reasons.append("POOLED_VEHICLE_ORIENTED")
    if values[SCORING_FIELDS[3]] is True:
        reasons.append("INSTITUTIONAL_ORIENTED")
    if values[SCORING_FIELDS[4]] is True:
        reasons.append("PENSION_CONSULTING_MODEL")
    if values[SCORING_FIELDS[5]] is True:
        reasons.append("MULTI_ADVISER_MODEL")

    score = None
    if not missing:
        score = round(
            min(
                max(
                    individual_points
                    + planning_points
                    - pooled_penalty
                    - institutional_penalty
                    - pension_penalty
                    - other_adviser_penalty,
                    0.0,
                ),
                MAX_SCORE,
            ),
            10,
        )
    return {
        "advisory_model_fit_score": score,
        "individual_model_points": individual_points,
        "financial_planning_points": planning_points,
        "pooled_vehicle_penalty": pooled_penalty,
        "institutional_penalty": institutional_penalty,
        "pension_penalty": pension_penalty,
        "other_adviser_penalty": other_adviser_penalty,
        "advisory_model_data_complete": not missing,
        "partially_scoreable": bool(missing and any(value is not None for value in values.values())),
        "advisory_model_reason_codes": reasons,
    }


def evaluate_advisory_model_fit(firms: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of ``firms`` with advisory-model component fields."""
    result = firms.copy()
    values = result.apply(
        lambda row: calculate_advisory_model_fit(
            *(row.get(field) for field in SCORING_FIELDS)
        ),
        axis=1,
        result_type="expand",
    )
    for field in (
        "advisory_model_fit_score",
        "individual_model_points",
        "financial_planning_points",
        "pooled_vehicle_penalty",
        "institutional_penalty",
        "pension_penalty",
        "other_adviser_penalty",
        "advisory_model_data_complete",
        "partially_scoreable",
    ):
        result[field] = values[field]
    result["advisory_model_reason_codes"] = values[
        "advisory_model_reason_codes"
    ].map(lambda codes: json.dumps(codes, separators=(",", ":")))
    return result

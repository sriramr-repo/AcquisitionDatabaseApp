"""Practice-complexity component for the redesigned Gold layer."""

import json
import math
from typing import Any, Optional

import pandas as pd


MAX_SCORE = 10.0
CONTROL_FIELDS = (
    "has_related_person_control",
    "under_common_control",
    "shares_supervised_persons",
    "shares_location",
    "has_unlisted_control_person",
)


def _numeric(value: Any) -> Optional[float]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


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


def _employee_score(employee_count: float) -> float:
    if employee_count <= 3:
        return 5.0
    if employee_count <= 10:
        return 4.0
    if employee_count <= 25:
        return 2.0
    return 0.0


def _advisory_score(advisory_employee_count: float) -> float:
    if advisory_employee_count <= 1:
        return 3.0
    if advisory_employee_count <= 3:
        return 2.0
    if advisory_employee_count <= 10:
        return 1.0
    return 0.0


def calculate_practice_complexity(
    employee_count: Any,
    advisory_employee_count: Any,
    *,
    has_related_person_control: Any,
    under_common_control: Any,
    shares_supervised_persons: Any,
    shares_location: Any,
    has_unlisted_control_person: Any,
) -> dict[str, Any]:
    """Calculate practice-complexity subscores without inferring ownership."""
    employees = _numeric(employee_count)
    advisory_employees = _numeric(advisory_employee_count)
    reasons: list[str] = []
    invalid = False

    employee_score: Optional[float] = None
    advisory_score: Optional[float] = None
    standalone_score: Optional[float] = None

    if employees is None or advisory_employees is None:
        reasons.append("MISSING_STAFFING_DATA")
    elif employees < 0 or advisory_employees < 0 or advisory_employees > employees:
        invalid = True
        reasons.append("INVALID_STAFFING_RELATIONSHIP")
    else:
        employee_score = _employee_score(employees)
        advisory_score = _advisory_score(advisory_employees)
        if employees <= 3:
            reasons.append("SMALL_EMPLOYEE_BASE")
        elif employees > 25:
            reasons.append("LARGE_EMPLOYEE_BASE")
        if advisory_employees <= 3:
            reasons.append("SMALL_ADVISORY_TEAM")
        elif advisory_employees > 10:
            reasons.append("LARGE_ADVISORY_TEAM")
        if employees == 0:
            reasons.append("ZERO_EMPLOYEE_COUNT_REVIEW")

    controls = [_boolean(locals()[field]) for field in CONTROL_FIELDS]
    if any(value is None for value in controls):
        reasons.append("MISSING_CONTROL_DATA")
    elif any(controls):
        standalone_score = 0.0
        reasons.append("COMPLEX_CONTROL_STRUCTURE")
    else:
        standalone_score = 2.0
        reasons.append("SIMPLE_CONTROL_STRUCTURE")

    if any(value is not None for value in (employee_score, advisory_score, standalone_score)):
        partial = True
    else:
        partial = False

    aggregate = None
    if not invalid and all(
        value is not None for value in (employee_score, advisory_score, standalone_score)
    ):
        aggregate = round(min(employee_score + advisory_score + standalone_score, MAX_SCORE), 10)
        partial = False

    reasons = list(dict.fromkeys(reasons))
    return {
        "employee_size_score": employee_score,
        "advisory_team_score": advisory_score,
        "standalone_structure_score": standalone_score,
        "practice_complexity_score": aggregate,
        "practice_complexity_data_complete": aggregate is not None,
        "partially_scoreable": partial,
        "invalid_staffing_relationship": invalid,
        "practice_complexity_reason_codes": reasons,
    }


def evaluate_practice_complexity(firms: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of ``firms`` with practice-complexity fields."""
    result = firms.copy()
    values = result.apply(
        lambda row: calculate_practice_complexity(
            row.get("employee_count"),
            row.get("advisory_employee_count"),
            **{field: row.get(field) for field in CONTROL_FIELDS},
        ),
        axis=1,
        result_type="expand",
    )
    for field in (
        "employee_size_score",
        "advisory_team_score",
        "standalone_structure_score",
        "practice_complexity_score",
        "practice_complexity_data_complete",
        "partially_scoreable",
        "invalid_staffing_relationship",
    ):
        result[field] = values[field]
    result["practice_complexity_reason_codes"] = values[
        "practice_complexity_reason_codes"
    ].map(lambda codes: json.dumps(codes, separators=(",", ":")))
    return result

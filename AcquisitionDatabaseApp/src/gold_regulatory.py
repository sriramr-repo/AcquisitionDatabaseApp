"""Regulatory-quality component based on precise Form ADV Item 11 counts."""

import json
from typing import Any, Optional

import pandas as pd


MAX_SCORE = 10.0

CONVICTION_FIELDS = (
    "felony_conviction_count",
    "misdemeanor_investment_or_fraud_conviction_count",
)
CHARGE_FIELDS = (
    "felony_charge_count",
    "misdemeanor_investment_or_fraud_charge_count",
)
REGULATORY_DISCLOSURE_FIELDS = (
    "sec_cftc_false_statement_count",
    "sec_cftc_violation_count",
    "sec_cftc_authorization_restriction_cause_count",
    "sec_cftc_investment_order_count",
    "sec_cftc_penalty_or_cease_desist_count",
    "other_regulator_false_statement_count",
    "other_regulator_violation_count",
    "other_regulator_authorization_restriction_cause_count",
    "other_regulator_investment_order_count",
    "other_regulator_registration_or_association_restriction_count",
    "sro_false_statement_count",
    "sro_rule_violation_count",
    "sro_authorization_restriction_cause_count",
    "sro_discipline_count",
    "professional_license_revocation_count",
)
CIVIL_ACTION_FIELDS = (
    "court_injunction_count",
    "court_investment_statute_violation_count",
    "settled_investment_civil_action_count",
)
PENDING_REGULATORY_FIELDS = ("pending_regulatory_proceeding_count",)
PENDING_CIVIL_FIELDS = ("pending_civil_proceeding_count",)

ALL_ITEM_11_COUNT_FIELDS = (
    CONVICTION_FIELDS
    + CHARGE_FIELDS
    + REGULATORY_DISCLOSURE_FIELDS
    + CIVIL_ACTION_FIELDS
    + PENDING_REGULATORY_FIELDS
    + PENDING_CIVIL_FIELDS
)


def _count(value: Any) -> Optional[float]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if number >= 0 else None


def _has_any(values: dict[str, Optional[float]], fields: tuple[str, ...]) -> bool:
    return any(values[field] is not None and values[field] > 0 for field in fields)


def calculate_regulatory_quality(**item_11_counts: Any) -> dict[str, Any]:
    """Calculate regulatory quality from Item 11 count fields only.

    Parent Item 11 indicators and duplicate Yes/No fields are intentionally not
    scoring inputs. Each penalty category is applied once regardless of event
    count or the number of fields populated within that category.
    """
    values = {field: _count(item_11_counts.get(field)) for field in ALL_ITEM_11_COUNT_FIELDS}
    missing = [field for field, value in values.items() if value is None]
    reasons: list[str] = []
    conviction = _has_any(values, CONVICTION_FIELDS)
    charge = _has_any(values, CHARGE_FIELDS)
    regulatory = _has_any(values, REGULATORY_DISCLOSURE_FIELDS)
    civil = _has_any(values, CIVIL_ACTION_FIELDS)
    pending_regulatory = _has_any(values, PENDING_REGULATORY_FIELDS)
    pending_civil = _has_any(values, PENDING_CIVIL_FIELDS)

    conviction_penalty = 4.0 if conviction else 0.0
    charge_penalty = 2.0 if charge else 0.0
    regulatory_disclosure_penalty = 2.0 if regulatory or civil else 0.0
    pending_proceeding_penalty = 3.0 if pending_regulatory or pending_civil else 0.0

    if missing:
        reasons.append("MISSING_REGULATORY_DATA")
    else:
        if conviction:
            reasons.append("CRIMINAL_CONVICTION_DISCLOSURE")
        if charge:
            reasons.append("CRIMINAL_CHARGE_DISCLOSURE")
        if regulatory:
            reasons.append("REGULATORY_DISCLOSURE")
        if civil:
            reasons.append("CIVIL_ACTION_DISCLOSURE")
        if pending_regulatory:
            reasons.append("PENDING_REGULATORY_PROCEEDING")
        if pending_civil:
            reasons.append("PENDING_CIVIL_PROCEEDING")
        if not reasons:
            reasons.append("CLEAN_ITEM11_HISTORY")

    score = None
    if not missing:
        score = max(
            0.0,
            MAX_SCORE
            - conviction_penalty
            - charge_penalty
            - regulatory_disclosure_penalty
            - pending_proceeding_penalty,
        )
    review_flag = bool(missing or conviction or charge or regulatory or civil or pending_regulatory or pending_civil)
    return {
        "regulatory_quality_score": score,
        "regulatory_review_flag": review_flag,
        "regulatory_quality_data_complete": not missing,
        "criminal_conviction_penalty": conviction_penalty,
        "criminal_charge_penalty": charge_penalty,
        "regulatory_disclosure_penalty": regulatory_disclosure_penalty,
        "pending_proceeding_penalty": pending_proceeding_penalty,
        "regulatory_quality_reason_codes": reasons,
    }


def evaluate_regulatory_quality(firms: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of ``firms`` with regulatory-quality component fields."""
    result = firms.copy()
    values = result.apply(
        lambda row: calculate_regulatory_quality(
            **{field: row.get(field) for field in ALL_ITEM_11_COUNT_FIELDS}
        ),
        axis=1,
        result_type="expand",
    )
    for field in (
        "regulatory_quality_score",
        "regulatory_review_flag",
        "regulatory_quality_data_complete",
        "criminal_conviction_penalty",
        "criminal_charge_penalty",
        "regulatory_disclosure_penalty",
        "pending_proceeding_penalty",
    ):
        result[field] = values[field]
    result["regulatory_quality_reason_codes"] = values[
        "regulatory_quality_reason_codes"
    ].map(lambda codes: json.dumps(codes, separators=(",", ":")))
    return result

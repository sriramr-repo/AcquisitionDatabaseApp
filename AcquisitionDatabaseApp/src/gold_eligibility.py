"""Versioned eligibility and AUM-fit primitives for the redesigned Gold layer.

This module intentionally does not write Gold tables or calculate the final
acquisition score. It provides an isolated DataFrame transformation that later
Gold components can extend.
"""

import json
import math
from typing import Any, Iterable, Optional

import pandas as pd


SCORE_VERSION = "SCM_ACQUISITION_V2"

# These are the only registration statuses observed in ia07012026.  Other
# values are deliberately treated as ambiguous until their semantics are
# confirmed, rather than being silently hard-excluded.
CURRENT_REGISTRATION_STATUSES = frozenset({"Approved"})
AMBIGUOUS_REGISTRATION_STATUSES = frozenset({"120-Day Approval"})

MIN_TARGET_AUM = 20_000_000.0
PREFERRED_MIN_AUM = 25_000_000.0
PREFERRED_MAX_AUM = 60_000_000.0
MAX_TARGET_AUM = 100_000_000.0


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    try:
        return bool(pd.isna(value))
    except (TypeError, ValueError):
        return False


def _numeric(value: Any) -> Optional[float]:
    if _is_missing(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def aum_fit_score(total_aum: Any) -> Optional[float]:
    """Return the 20-point AUM-fit score, or None when not scoreable."""
    aum = _numeric(total_aum)
    if aum is None or not MIN_TARGET_AUM <= aum <= MAX_TARGET_AUM:
        return None
    if aum <= PREFERRED_MIN_AUM:
        score = 12.0 + (aum - MIN_TARGET_AUM) / (PREFERRED_MIN_AUM - MIN_TARGET_AUM) * 8.0
    elif aum <= PREFERRED_MAX_AUM:
        score = 20.0
    else:
        score = 20.0 - (aum - PREFERRED_MAX_AUM) / (MAX_TARGET_AUM - PREFERRED_MAX_AUM) * 12.0
    return round(score, 10)


def _status(value: Any) -> Optional[str]:
    if _is_missing(value):
        return None
    return str(value).strip()


def _reason_codes(row: pd.Series) -> list[str]:
    codes: list[str] = []
    aum = _numeric(row.get("total_aum"))
    if aum is not None and MIN_TARGET_AUM <= aum <= MAX_TARGET_AUM:
        if PREFERRED_MIN_AUM <= aum <= PREFERRED_MAX_AUM:
            codes.append("PREFERRED_AUM_BAND")
        else:
            codes.append("TARGET_AUM_BAND")
    elif aum is not None:
        codes.append("OUTSIDE_AUM_MANDATE")

    if row.get("eligibility_status") == "REVIEW_REQUIRED":
        if row.get("status_review_required"):
            codes.append("AMBIGUOUS_REGISTRATION_STATUS")
        if row.get("core_data_review_required"):
            codes.append("MISSING_CORE_DATA")
    if row.get("hard_exclusion_reason") == "STRUCTURAL_DATA_QUALITY_FAILURE":
        codes.append("STRUCTURAL_DATA_QUALITY_FAILURE")
    return list(dict.fromkeys(codes))


def evaluate_eligibility(
    firms: pd.DataFrame,
    *,
    non_current_statuses: Iterable[str] = (),
) -> pd.DataFrame:
    """Evaluate eligibility and AUM fit without writing production outputs.

    ``non_current_statuses`` is explicit so a future confirmed status mapping
    can be supplied without changing the scoring code. No such statuses were
    observed in the current production Silver dataset.
    """
    result = firms.copy()
    non_current = {str(status).strip() for status in non_current_statuses}

    required_columns = {"firm_id", "total_aum"}
    has_required_columns = required_columns.issubset(result.columns)
    if not has_required_columns:
        result["eligibility_status"] = "EXCLUDED"
        result["review_required"] = False
        result["hard_exclusion_reason"] = "STRUCTURAL_DATA_QUALITY_FAILURE"
        result["aum_fit_score"] = None
        result["score_version"] = SCORE_VERSION
        result["status_review_required"] = False
        result["core_data_review_required"] = False
        result["reason_codes"] = json.dumps(["STRUCTURAL_DATA_QUALITY_FAILURE"])
        return result

    statuses = result.get("sec_current_status", pd.Series(index=result.index, dtype=object)).map(_status)
    missing_id = result["firm_id"].map(_is_missing)
    missing_aum = result["total_aum"].map(_numeric).isna()
    numeric_aum = result["total_aum"].map(_numeric)
    # AUM outside the historical SCM target band remains a transparent
    # screening signal, but is not a hard eligibility exclusion. The band
    # can guide prioritization and research without discarding other paths.
    outside_aum = numeric_aum.notna() & ~numeric_aum.between(MIN_TARGET_AUM, MAX_TARGET_AUM)
    explicit_non_current = statuses.isin(non_current)
    ambiguous_status = statuses.notna() & ~statuses.isin(CURRENT_REGISTRATION_STATUSES | non_current)
    missing_status = statuses.isna()

    structural_failure = missing_id
    missing_core = missing_aum
    hard_reason = pd.Series([None] * len(result), index=result.index, dtype=object)
    hard_reason.loc[structural_failure] = "STRUCTURAL_DATA_QUALITY_FAILURE"
    hard_reason.loc[~structural_failure & missing_core] = "MISSING_CORE_DATA"
    hard_reason.loc[~structural_failure & ~missing_core & explicit_non_current] = "NON_CURRENT_REGISTRATION"
    # Outside-band AUM is intentionally not assigned to hard_reason. Missing
    # core data, structural failures, and confirmed non-current statuses
    # remain hard exclusions.

    hard_excluded = hard_reason.notna()
    status_review = ~hard_excluded & (ambiguous_status | missing_status)
    core_review = pd.Series(False, index=result.index)
    review_required = ~hard_excluded & (status_review | core_review)

    result["score_version"] = SCORE_VERSION
    result["eligibility_status"] = "ELIGIBLE"
    result.loc[review_required, "eligibility_status"] = "REVIEW_REQUIRED"
    result.loc[hard_excluded, "eligibility_status"] = "EXCLUDED"
    result["review_required"] = review_required
    result["hard_exclusion_reason"] = hard_reason
    result["status_review_required"] = status_review
    result["core_data_review_required"] = core_review
    result["aum_fit_score"] = numeric_aum.map(aum_fit_score)
    result.loc[hard_excluded, "aum_fit_score"] = None
    result["reason_codes"] = result.apply(
        lambda row: json.dumps(_reason_codes(row), separators=(",", ":")), axis=1
    )
    return result

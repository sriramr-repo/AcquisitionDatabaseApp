"""Account/practice-fit component for the redesigned Gold layer."""

import json
import math
from typing import Any, Optional

import pandas as pd


MAX_SCORE = 14.0
MANAGEABLE_ACCOUNT_LIMIT = 500
HIGH_ACCOUNT_COUNT_LIMIT = 2_000
HIGH_AVERAGE_ACCOUNT_SIZE = 500_000.0
LOW_AVERAGE_ACCOUNT_SIZE = 100_000.0
HIGH_DISCRETIONARY_ACCOUNT_SHARE = 0.75
LOW_DISCRETIONARY_ACCOUNT_SHARE = 0.50


def _numeric(value: Any) -> Optional[float]:
    if value is None or (isinstance(value, str) and not value.strip()):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _account_count_score(account_count: float) -> float:
    if account_count <= 100:
        return 6.0
    if account_count <= 500:
        return 4.0
    if account_count <= HIGH_ACCOUNT_COUNT_LIMIT:
        return 2.0
    return 0.0


def calculate_account_practice_fit(
    total_aum: Any,
    total_account_count: Any,
    discretionary_account_count: Any,
) -> dict[str, Any]:
    """Calculate account/practice subcomponents for one firm.

    A zero or negative total account count makes every account-derived
    subcomponent unavailable. This avoids treating a zero account count as an
    ideal small practice while preserving valid zero discretionary accounts.
    Missing or invalid subcomponents remain unavailable; the aggregate
    component score is None unless all three subscores are available.
    """
    aum = _numeric(total_aum)
    accounts = _numeric(total_account_count)
    discretionary_accounts = _numeric(discretionary_account_count)
    reasons: list[str] = []
    invalid = False

    account_score: Optional[float] = None
    average_account_size: Optional[float] = None
    average_score: Optional[float] = None
    discretionary_share: Optional[float] = None
    discretionary_score: Optional[float] = None

    if accounts is None or accounts <= 0:
        reasons.append("MISSING_ACCOUNT_DATA")
        if accounts is not None and accounts < 0:
            invalid = True
            reasons = ["INVALID_ACCOUNT_RELATIONSHIP"]
    else:
        account_score = _account_count_score(accounts)
        if accounts <= MANAGEABLE_ACCOUNT_LIMIT:
            reasons.append("MANAGEABLE_ACCOUNT_BASE")
        elif accounts > HIGH_ACCOUNT_COUNT_LIMIT:
            reasons.append("HIGH_ACCOUNT_COUNT")

        if aum is not None and aum >= 0:
            average_account_size = aum / accounts
            average_score = min(max(5.0 * average_account_size / HIGH_AVERAGE_ACCOUNT_SIZE, 0.0), 5.0)
            if average_account_size >= HIGH_AVERAGE_ACCOUNT_SIZE:
                reasons.append("HIGH_AVERAGE_ACCOUNT_SIZE")
            elif average_account_size < LOW_AVERAGE_ACCOUNT_SIZE:
                reasons.append("LOW_AVERAGE_ACCOUNT_SIZE")
        else:
            reasons.append("MISSING_ACCOUNT_DATA")
            if aum is not None and aum < 0:
                invalid = True
                reasons.append("INVALID_ACCOUNT_RELATIONSHIP")

        if discretionary_accounts is None:
            reasons.append("MISSING_ACCOUNT_DATA")
        elif discretionary_accounts < 0 or discretionary_accounts > accounts:
            invalid = True
            reasons.append("INVALID_ACCOUNT_RELATIONSHIP")
        else:
            discretionary_share = min(max(discretionary_accounts / accounts, 0.0), 1.0)
            discretionary_score = 3.0 * discretionary_share
            if discretionary_share >= HIGH_DISCRETIONARY_ACCOUNT_SHARE:
                reasons.append("HIGH_DISCRETIONARY_ACCOUNT_SHARE")
            elif discretionary_share < LOW_DISCRETIONARY_ACCOUNT_SHARE:
                reasons.append("LOW_DISCRETIONARY_ACCOUNT_SHARE")

    reasons = list(dict.fromkeys(reasons))
    subscores = [account_score, average_score, discretionary_score]
    aggregate = None
    if not invalid and all(score is not None for score in subscores):
        aggregate = round(min(sum(subscores), MAX_SCORE), 10)
    partial = aggregate is None and any(score is not None for score in subscores)
    return {
        "average_account_size": average_account_size,
        "discretionary_account_share": discretionary_share,
        "account_count_component_score": account_score,
        "average_account_size_component_score": average_score,
        "discretionary_account_share_component_score": discretionary_score,
        "account_practice_fit_score": aggregate,
        "partially_scoreable": partial,
        "invalid_account_relationship": invalid,
        "reason_codes": reasons,
    }


def evaluate_account_practice_fit(firms: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of ``firms`` with account/practice-fit fields."""
    result = firms.copy()
    values = result.apply(
        lambda row: calculate_account_practice_fit(
            row.get("total_aum"),
            row.get("total_account_count"),
            row.get("discretionary_account_count"),
        ),
        axis=1,
        result_type="expand",
    )
    for field in (
        "average_account_size",
        "discretionary_account_share",
        "account_count_component_score",
        "average_account_size_component_score",
        "discretionary_account_share_component_score",
        "account_practice_fit_score",
        "partially_scoreable",
        "invalid_account_relationship",
    ):
        result[field] = values[field]
    result["account_practice_reason_codes"] = values["reason_codes"].map(
        lambda codes: json.dumps(codes, separators=(",", ":"))
    )
    return result

import json

import pandas as pd

from src.gold_eligibility import (
    SCORE_VERSION,
    aum_fit_score,
    evaluate_eligibility,
)


def firm(**overrides):
    row = {
        "firm_id": "123",
        "total_aum": 25_000_000,
        "sec_current_status": "Approved",
    }
    row.update(overrides)
    return pd.DataFrame([row])


def result(**overrides):
    return evaluate_eligibility(firm(**overrides)).iloc[0]


def test_aum_boundaries():
    expected = {
        19_999_999: None,
        20_000_000: 12.0,
        22_500_000: 16.0,
        25_000_000: 20.0,
        60_000_000: 20.0,
        80_000_000: 14.0,
        100_000_000: 8.0,
        100_000_001: None,
    }
    assert {aum: aum_fit_score(aum) for aum in expected} == expected


def test_eligibility_statuses_and_version():
    eligible = result(total_aum=40_000_000)
    assert eligible.eligibility_status == "ELIGIBLE"
    assert bool(eligible.review_required) is False
    assert eligible.hard_exclusion_reason is None
    assert eligible.score_version == SCORE_VERSION

    ambiguous = result(total_aum=40_000_000, sec_current_status="120-Day Approval")
    assert ambiguous.eligibility_status == "REVIEW_REQUIRED"
    assert bool(ambiguous.review_required) is True
    assert "AMBIGUOUS_REGISTRATION_STATUS" in json.loads(ambiguous.reason_codes)

    non_current = result(total_aum=40_000_000, sec_current_status="Withdrawn")
    assert non_current.eligibility_status == "REVIEW_REQUIRED"

    confirmed_non_current = evaluate_eligibility(
        firm(total_aum=40_000_000, sec_current_status="Withdrawn"),
        non_current_statuses={"Withdrawn"},
    ).iloc[0]
    assert confirmed_non_current.eligibility_status == "EXCLUDED"
    assert confirmed_non_current.hard_exclusion_reason == "NON_CURRENT_REGISTRATION"


def test_aum_reason_codes_and_exclusions():
    preferred = result(total_aum=30_000_000)
    assert json.loads(preferred.reason_codes) == ["PREFERRED_AUM_BAND"]

    target = result(total_aum=22_000_000)
    assert json.loads(target.reason_codes) == ["TARGET_AUM_BAND"]

    outside = result(total_aum=19_999_999)
    assert outside.eligibility_status == "ELIGIBLE"
    assert outside.hard_exclusion_reason is None
    assert outside.aum_fit_score is None
    assert json.loads(outside.reason_codes) == ["OUTSIDE_AUM_MANDATE"]


def test_missing_core_values_are_not_coerced_to_zero():
    missing_aum = result(total_aum=None)
    assert missing_aum.eligibility_status == "EXCLUDED"
    assert missing_aum.hard_exclusion_reason == "MISSING_CORE_DATA"
    assert missing_aum.aum_fit_score is None

    missing_id = result(firm_id="")
    assert missing_id.eligibility_status == "EXCLUDED"
    assert missing_id.hard_exclusion_reason == "STRUCTURAL_DATA_QUALITY_FAILURE"


def test_missing_required_columns_is_structural_failure():
    output = evaluate_eligibility(pd.DataFrame([{"total_aum": 25_000_000}])).iloc[0]
    assert output.eligibility_status == "EXCLUDED"
    assert output.hard_exclusion_reason == "STRUCTURAL_DATA_QUALITY_FAILURE"

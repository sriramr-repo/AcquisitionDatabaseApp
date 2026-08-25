import json

import pandas as pd

from src.gold_regulatory import ALL_ITEM_11_COUNT_FIELDS, calculate_regulatory_quality, evaluate_regulatory_quality


def clean_values(**overrides):
    values = {field: 0 for field in ALL_ITEM_11_COUNT_FIELDS}
    values.update(overrides)
    return values


def test_clean_history_and_zero_are_distinct_from_missing():
    clean = calculate_regulatory_quality(**clean_values())
    missing = calculate_regulatory_quality(**clean_values(felony_conviction_count=None))

    assert clean["regulatory_quality_score"] == 10.0
    assert clean["regulatory_review_flag"] is False
    assert clean["regulatory_quality_reason_codes"] == ["CLEAN_ITEM11_HISTORY"]
    assert missing["regulatory_quality_score"] is None
    assert missing["regulatory_review_flag"] is True
    assert missing["regulatory_quality_reason_codes"] == ["MISSING_REGULATORY_DATA"]


def test_each_penalty_category_applies_once():
    conviction = calculate_regulatory_quality(**clean_values(felony_conviction_count=4, misdemeanor_investment_or_fraud_conviction_count=2))
    charge = calculate_regulatory_quality(**clean_values(felony_charge_count=3, misdemeanor_investment_or_fraud_charge_count=2))
    regulatory = calculate_regulatory_quality(**clean_values(sec_cftc_violation_count=5, sro_discipline_count=9))
    civil = calculate_regulatory_quality(**clean_values(court_injunction_count=2))
    pending = calculate_regulatory_quality(**clean_values(pending_regulatory_proceeding_count=4, pending_civil_proceeding_count=3))

    assert conviction["regulatory_quality_score"] == 6.0
    assert charge["regulatory_quality_score"] == 8.0
    assert regulatory["regulatory_quality_score"] == 8.0
    assert civil["regulatory_quality_score"] == 8.0
    assert pending["regulatory_quality_score"] == 7.0


def test_combined_penalties_floor_at_zero_and_reasons_are_specific():
    output = calculate_regulatory_quality(
        **clean_values(
            felony_conviction_count=1,
            felony_charge_count=1,
            sec_cftc_violation_count=1,
            court_injunction_count=1,
            pending_regulatory_proceeding_count=1,
            pending_civil_proceeding_count=1,
        )
    )
    assert output["regulatory_quality_score"] == 0.0
    assert output["regulatory_review_flag"] is True
    assert set(output["regulatory_quality_reason_codes"]) == {
        "CRIMINAL_CONVICTION_DISCLOSURE",
        "CRIMINAL_CHARGE_DISCLOSURE",
        "REGULATORY_DISCLOSURE",
        "CIVIL_ACTION_DISCLOSURE",
        "PENDING_REGULATORY_PROCEEDING",
        "PENDING_CIVIL_PROCEEDING",
    }


def test_parent_indicator_does_not_double_count_count_fields():
    base = pd.DataFrame([{**clean_values(felony_conviction_count=1), "has_item_11_disclosure": True}])
    output = evaluate_regulatory_quality(base).iloc[0]
    assert output.regulatory_quality_score == 6.0
    assert output.criminal_conviction_penalty == 4.0


def test_dataframe_interface_isolated():
    row = clean_values(felony_charge_count=1)
    output = evaluate_regulatory_quality(pd.DataFrame([row]))
    assert output.loc[0, "regulatory_quality_score"] == 8.0
    assert json.loads(output.loc[0, "regulatory_quality_reason_codes"]) == [
        "CRIMINAL_CHARGE_DISCLOSURE"
    ]

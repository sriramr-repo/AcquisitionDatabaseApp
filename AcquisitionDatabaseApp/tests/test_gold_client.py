import json

import pandas as pd

from src.gold_client import MAX_SCORE, calculate_client_fit, evaluate_client_fit


def test_approved_formula_examples():
    assert calculate_client_fit(100, 50, 100)["client_fit_score"] == 15.0
    assert calculate_client_fit(80, 30, 100)["client_fit_score"] == 11.4
    assert calculate_client_fit(100, 100, 100)["client_fit_score"] == 18.0
    assert calculate_client_fit(0, 0, 100)["client_fit_score"] == 0.0


def test_missing_values_remain_unavailable_and_zero_is_distinct():
    missing_individual = calculate_client_fit(None, 10, 100)
    missing_hnw = calculate_client_fit(50, None, 100)
    missing_total = calculate_client_fit(50, 10, None)
    zero = calculate_client_fit(0, 0, 100)

    assert missing_individual["client_fit_score"] is None
    assert missing_hnw["client_fit_score"] is None
    assert missing_total["client_fit_score"] is None
    assert missing_individual["individual_hnw_share"] is None
    assert missing_hnw["hnw_share"] is None
    assert "MISSING_CLIENT_MIX_DATA" in missing_individual["reason_codes"]
    assert zero["client_fit_score"] == 0.0
    assert zero["individual_hnw_share"] == 0.0
    assert "LOW_INDIVIDUAL_HNW_SHARE" in zero["reason_codes"]


def test_invalid_client_relationships_are_flagged_and_not_scored():
    for values in [
        (101, 10, 100),
        (50, 101, 100),
        (50, 60, 100),
        (-1, 0, 100),
        (1, 0, 0),
    ]:
        output = calculate_client_fit(*values)
        assert output["client_fit_score"] is None
        assert output["individual_hnw_share"] is None
        assert output["hnw_share"] is None
        assert output["invalid_client_aum_relationship"] is True
        assert output["reason_codes"] == ["INVALID_CLIENT_AUM_RELATIONSHIP"]


def test_reason_thresholds_and_score_cap():
    focused = calculate_client_fit(75, 50, 100)
    individual = calculate_client_fit(50, 10, 100)
    low = calculate_client_fit(49, 10, 100)

    assert "HNW_INDIVIDUAL_FOCUSED" in focused["reason_codes"]
    assert "HIGH_HNW_AUM_SHARE" in focused["reason_codes"]
    assert "INDIVIDUAL_CLIENT_FOCUSED" in individual["reason_codes"]
    assert "HNW_INDIVIDUAL_FOCUSED" not in individual["reason_codes"]
    assert "LOW_INDIVIDUAL_HNW_SHARE" in low["reason_codes"]
    assert low["client_fit_score"] <= MAX_SCORE


def test_dataframe_interface_isolated():
    firms = pd.DataFrame(
        [
            {
                "firm_id": "1",
                "individual_hnw_client_aum": 100,
                "hnw_client_aum": 50,
                "total_aum": 100,
            },
            {
                "firm_id": "2",
                "individual_hnw_client_aum": None,
                "hnw_client_aum": 10,
                "total_aum": 100,
            },
        ]
    )
    output = evaluate_client_fit(firms)
    assert len(output) == 2
    assert output.loc[0, "client_fit_score"] == 15.0
    assert pd.isna(output.loc[1, "client_fit_score"])
    assert json.loads(output.loc[1, "client_fit_reason_codes"]) == [
        "MISSING_CLIENT_MIX_DATA"
    ]

import json

import pandas as pd

from src.gold_discretionary import (
    MAX_SCORE,
    calculate_discretionary_fit,
    evaluate_discretionary_fit,
)


def test_approved_formula_examples():
    assert calculate_discretionary_fit(25_000_000, 25_000_000)["discretionary_fit_score"] == 18.0
    assert calculate_discretionary_fit(80_000_000, 100_000_000)["discretionary_fit_score"] == 15.0
    assert calculate_discretionary_fit(10_000_000, 20_000_000)["discretionary_fit_score"] == 8.7
    assert calculate_discretionary_fit(0, 20_000_000)["discretionary_fit_score"] == 0.0


def test_missing_values_remain_unavailable_and_zero_is_distinct():
    missing_discretionary = calculate_discretionary_fit(None, 20_000_000)
    missing_total = calculate_discretionary_fit(10_000_000, None)
    zero = calculate_discretionary_fit(0, 20_000_000)

    assert missing_discretionary["discretionary_fit_score"] is None
    assert missing_total["discretionary_fit_score"] is None
    assert "MISSING_DISCRETIONARY_DATA" in missing_discretionary["reason_codes"]
    assert zero["discretionary_fit_score"] == 0.0
    assert zero["discretionary_share"] == 0.0
    assert "LOW_DISCRETIONARY_SHARE" in zero["reason_codes"]


def test_invalid_relationships_are_flagged_and_not_scored():
    for discretionary, total in [
        (25_000_001, 25_000_000),
        (-1, 25_000_000),
        (1, 0),
    ]:
        output = calculate_discretionary_fit(discretionary, total)
        assert output["discretionary_fit_score"] is None
        assert output["discretionary_share"] is None
        assert output["invalid_discretionary_aum_relationship"] is True
        assert output["reason_codes"] == ["INVALID_DISCRETIONARY_AUM_RELATIONSHIP"]


def test_reason_thresholds_and_score_cap():
    high = calculate_discretionary_fit(30_000_000, 30_000_000)
    predominant = calculate_discretionary_fit(15_000_000, 20_000_000)
    low = calculate_discretionary_fit(9_000_000, 20_000_000)

    assert {"HIGH_DISCRETIONARY_SHARE", "PREDOMINANTLY_DISCRETIONARY", "MEANINGFUL_DISCRETIONARY_AUM"}.issubset(high["reason_codes"])
    assert "PREDOMINANTLY_DISCRETIONARY" in predominant["reason_codes"]
    assert "HIGH_DISCRETIONARY_SHARE" not in predominant["reason_codes"]
    assert "LOW_DISCRETIONARY_SHARE" in low["reason_codes"]
    assert high["discretionary_fit_score"] <= MAX_SCORE


def test_dataframe_interface_isolated():
    firms = pd.DataFrame(
        [
            {"firm_id": "1", "discretionary_aum": 25_000_000, "total_aum": 25_000_000},
            {"firm_id": "2", "discretionary_aum": None, "total_aum": 25_000_000},
        ]
    )
    output = evaluate_discretionary_fit(firms)
    assert len(output) == 2
    assert output.loc[0, "discretionary_fit_score"] == 18.0
    assert pd.isna(output.loc[1, "discretionary_fit_score"])
    assert json.loads(output.loc[1, "discretionary_reason_codes"]) == [
        "MISSING_DISCRETIONARY_DATA"
    ]

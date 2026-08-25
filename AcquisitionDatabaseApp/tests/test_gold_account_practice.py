import json

import pandas as pd

from src.gold_account_practice import (
    MAX_SCORE,
    calculate_account_practice_fit,
    evaluate_account_practice_fit,
)


def test_account_count_boundaries():
    expected = {
        0: None,
        1: 6.0,
        100: 6.0,
        101: 4.0,
        500: 4.0,
        501: 2.0,
        2000: 2.0,
        2001: 0.0,
    }
    for count, score in expected.items():
        output = calculate_account_practice_fit(100_000_000, count, 0 if count else 0)
        assert output["account_count_component_score"] == score


def test_average_account_size_scores():
    assert calculate_account_practice_fit(100_000, 1, 1)["average_account_size_component_score"] == 1.0
    assert calculate_account_practice_fit(250_000, 1, 1)["average_account_size_component_score"] == 2.5
    assert calculate_account_practice_fit(500_000, 1, 1)["average_account_size_component_score"] == 5.0
    assert calculate_account_practice_fit(1_000_000, 1, 1)["average_account_size_component_score"] == 5.0


def test_discretionary_account_share_scores():
    assert calculate_account_practice_fit(100, 100, 100)["discretionary_account_share_component_score"] == 3.0
    assert calculate_account_practice_fit(100, 100, 75)["discretionary_account_share_component_score"] == 2.25
    assert calculate_account_practice_fit(100, 100, 50)["discretionary_account_share_component_score"] == 1.5
    assert calculate_account_practice_fit(100, 100, 0)["discretionary_account_share_component_score"] == 0.0


def test_zero_accounts_are_unavailable_not_ideal():
    output = calculate_account_practice_fit(100_000_000, 0, 0)
    assert output["account_count_component_score"] is None
    assert output["average_account_size"] is None
    assert output["discretionary_account_share"] is None
    assert output["account_practice_fit_score"] is None
    assert output["partially_scoreable"] is False
    assert "MISSING_ACCOUNT_DATA" in output["reason_codes"]


def test_missing_values_remain_unavailable_and_partial_score_is_not_aggregate():
    missing_accounts = calculate_account_practice_fit(100_000_000, None, 10)
    missing_aum = calculate_account_practice_fit(None, 100, 50)
    missing_discretionary = calculate_account_practice_fit(100_000_000, 100, None)

    assert missing_accounts["account_practice_fit_score"] is None
    assert missing_aum["average_account_size_component_score"] is None
    assert missing_discretionary["discretionary_account_share"] is None
    assert missing_discretionary["account_practice_fit_score"] is None
    assert missing_discretionary["partially_scoreable"] is True


def test_invalid_relationships_are_flagged():
    for values in [
        (100_000_000, -1, 0),
        (100_000_000, 100, 101),
        (-1, 100, 50),
    ]:
        output = calculate_account_practice_fit(*values)
        assert output["invalid_account_relationship"] is True
        assert output["account_practice_fit_score"] is None
        assert "INVALID_ACCOUNT_RELATIONSHIP" in output["reason_codes"]


def test_reason_thresholds_and_score_cap():
    output = calculate_account_practice_fit(50_000_000, 100, 75)
    assert "MANAGEABLE_ACCOUNT_BASE" in output["reason_codes"]
    assert "HIGH_DISCRETIONARY_ACCOUNT_SHARE" in output["reason_codes"]
    assert output["account_practice_fit_score"] <= MAX_SCORE

    high_count = calculate_account_practice_fit(10_000_000, 2_001, 0)
    assert "HIGH_ACCOUNT_COUNT" in high_count["reason_codes"]
    assert "LOW_AVERAGE_ACCOUNT_SIZE" in high_count["reason_codes"]


def test_dataframe_interface_isolated():
    firms = pd.DataFrame(
        [{"firm_id": "1", "total_aum": 50_000_000, "total_account_count": 100, "discretionary_account_count": 100}]
    )
    output = evaluate_account_practice_fit(firms)
    assert len(output) == 1
    assert output.loc[0, "account_practice_fit_score"] == 14.0
    assert json.loads(output.loc[0, "account_practice_reason_codes"]) == [
        "MANAGEABLE_ACCOUNT_BASE",
        "HIGH_AVERAGE_ACCOUNT_SIZE",
        "HIGH_DISCRETIONARY_ACCOUNT_SHARE",
    ]

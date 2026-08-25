import json

import pandas as pd

from src.gold_advisory_model import MAX_SCORE, calculate_advisory_model_fit, evaluate_advisory_model_fit


FALSE_FLAGS = (False, False, False, False, False, False)


def calculate(*values):
    return calculate_advisory_model_fit(*values)


def test_approved_positive_and_negative_logic():
    assert calculate(True, False, False, False, False, False)["advisory_model_fit_score"] == 6.0
    assert calculate(True, True, False, False, False, False)["advisory_model_fit_score"] == 8.0
    assert calculate(True, True, True, False, False, False)["advisory_model_fit_score"] == 7.0
    assert calculate(False, False, False, True, False, False)["advisory_model_fit_score"] == 0.0
    assert calculate(False, False, True, False, False, False)["advisory_model_fit_score"] == 0.0
    assert calculate(False, False, False, False, True, False)["advisory_model_fit_score"] == 0.0
    assert calculate(False, False, False, False, False, True)["advisory_model_fit_score"] == 0.0


def test_all_flags_and_score_clamps():
    output = calculate(True, True, True, True, True, True)
    assert output["advisory_model_fit_score"] == 4.0
    assert output["advisory_model_fit_score"] <= MAX_SCORE
    for code in (
        "INDIVIDUAL_SMALL_BUSINESS_MODEL",
        "FINANCIAL_PLANNING_MODEL",
        "POOLED_VEHICLE_ORIENTED",
        "INSTITUTIONAL_ORIENTED",
        "PENSION_CONSULTING_MODEL",
        "MULTI_ADVISER_MODEL",
    ):
        assert code in output["advisory_model_reason_codes"]


def test_missing_flags_remain_unavailable_and_false_is_zero():
    missing = calculate(True, None, False, False, False, False)
    false = calculate(*FALSE_FLAGS)

    assert missing["advisory_model_fit_score"] is None
    assert missing["advisory_model_data_complete"] is False
    assert missing["partially_scoreable"] is True
    assert "MISSING_ADVISORY_MODEL_DATA" in missing["advisory_model_reason_codes"]
    assert false["advisory_model_fit_score"] == 0.0
    assert false["advisory_model_reason_codes"] == []


def test_reason_code_combinations():
    output = calculate(True, True, False, True, False, True)
    assert output["advisory_model_reason_codes"] == [
        "INDIVIDUAL_SMALL_BUSINESS_MODEL",
        "FINANCIAL_PLANNING_MODEL",
        "INSTITUTIONAL_ORIENTED",
        "MULTI_ADVISER_MODEL",
    ]


def test_dataframe_interface_isolated():
    firms = pd.DataFrame(
        [{
            "firm_id": "1",
            "advises_individuals_or_small_businesses": True,
            "provides_financial_planning": True,
            "advises_pooled_investment_vehicles": False,
            "advises_institutional_clients": False,
            "provides_pension_consulting": False,
            "selects_other_advisers": False,
        }]
    )
    output = evaluate_advisory_model_fit(firms)
    assert output.loc[0, "advisory_model_fit_score"] == 8.0
    assert json.loads(output.loc[0, "advisory_model_reason_codes"]) == [
        "INDIVIDUAL_SMALL_BUSINESS_MODEL",
        "FINANCIAL_PLANNING_MODEL",
    ]

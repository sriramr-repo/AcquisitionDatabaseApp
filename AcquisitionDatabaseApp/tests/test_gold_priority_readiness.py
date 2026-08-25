import json

import pandas as pd

from src.gold_priority_readiness import evaluate_priority_readiness


def base_row(**overrides):
    row = {
        "eligibility_status": "ELIGIBLE",
        "hard_exclusion_reason": None,
        "review_required": False,
        "status_review_required": False,
        "regulatory_review_flag": False,
        "score_completeness_pct": 100.0,
        "aum_fit_score": 20.0,
        "discretionary_fit_score": 18.0,
        "client_fit_score": 18.0,
        "account_practice_fit_score": 14.0,
        "regulatory_quality_score": 10.0,
        "acquisition_score": 100.0,
        "invalid_discretionary_aum_relationship": False,
        "invalid_client_aum_relationship": False,
        "invalid_account_relationship": False,
    }
    row.update(overrides)
    return pd.DataFrame([row])


def evaluate(**overrides):
    return evaluate_priority_readiness(base_row(**overrides)).iloc[0]


def test_complete_clean_firm_is_priority_ready():
    output = evaluate()
    assert output.priority_readiness == "PRIORITY_READY"
    assert bool(output.priority_ready) is True
    assert json.loads(output.priority_readiness_reason_codes) == ["PRIORITY_DATA_COMPLETE"]


def test_missing_client_blocks_readiness_without_changing_score():
    output = evaluate(client_fit_score=None, score_completeness_pct=82.0, acquisition_score=97.0)
    assert output.priority_readiness == "REVIEW_BEFORE_PRIORITY"
    assert bool(output.priority_ready) is False
    assert output.acquisition_score == 97.0
    assert json.loads(output.missing_material_components) == ["client_fit_score"]
    assert json.loads(output.priority_readiness_reason_codes) == [
        "MISSING_MATERIAL_CLIENT_DATA",
        "INSUFFICIENT_PRIORITY_COMPLETENESS",
    ]


def test_completeness_boundary():
    assert bool(evaluate(score_completeness_pct=89.99).priority_ready) is False
    assert bool(evaluate(score_completeness_pct=90.00).priority_ready) is True
    assert bool(evaluate(score_completeness_pct=100.00).priority_ready) is True


def test_regulatory_and_registration_review_block_readiness():
    regulatory = evaluate(regulatory_review_flag=True)
    registration = evaluate(status_review_required=True)
    assert regulatory.priority_readiness == "REVIEW_BEFORE_PRIORITY"
    assert "REGULATORY_REVIEW_REQUIRED" in json.loads(regulatory.priority_readiness_reason_codes)
    assert registration.priority_readiness == "REVIEW_BEFORE_PRIORITY"
    assert "REGISTRATION_REVIEW_REQUIRED" in json.loads(registration.priority_readiness_reason_codes)


def test_hard_exclusion_takes_precedence():
    output = evaluate(eligibility_status="EXCLUDED", hard_exclusion_reason="OUTSIDE_AUM_MANDATE")
    assert output.priority_readiness == "NOT_PRIORITY_ELIGIBLE"
    assert bool(output.priority_ready) is False


def test_multiple_missing_material_and_invalid_data():
    output = evaluate(
        client_fit_score=None,
        regulatory_quality_score=None,
        invalid_account_relationship=True,
        score_completeness_pct=64.0,
    )
    assert json.loads(output.missing_material_components) == [
        "client_fit_score",
        "regulatory_quality_score",
    ]
    assert "MISSING_MATERIAL_CLIENT_DATA" in json.loads(output.priority_readiness_reason_codes)
    assert "MISSING_MATERIAL_DATA" in json.loads(output.priority_readiness_reason_codes)
    assert "INVALID_MATERIAL_SCORING_DATA" in json.loads(output.priority_readiness_reason_codes)


def test_dataframe_evaluation_preserves_numeric_score():
    frame = base_row(acquisition_score=95.5)
    output = evaluate_priority_readiness(frame)
    assert output.loc[0, "acquisition_score"] == 95.5
    assert output.loc[0, "priority_readiness"] == "PRIORITY_READY"

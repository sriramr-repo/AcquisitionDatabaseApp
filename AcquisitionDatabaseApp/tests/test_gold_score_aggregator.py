import json

import pandas as pd

from src.gold_score_aggregator import COMPONENT_WEIGHTS, calculate_acquisition_score, evaluate_acquisition_scores


def full_scores(value=0):
    return {field: value for field in COMPONENT_WEIGHTS}


def test_complete_scores_sum_to_100_and_zero_is_valid():
    maximum = calculate_acquisition_score({field: weight for field, weight in COMPONENT_WEIGHTS.items()})
    zero = calculate_acquisition_score(full_scores(0))
    assert maximum["acquisition_score"] == 100.0
    assert zero["acquisition_score"] == 0.0
    assert maximum["score_completeness_pct"] == 100.0


def test_missing_component_uses_observed_weight_normalization():
    scores = full_scores(0)
    scores["client_fit_score"] = None
    output = calculate_acquisition_score(scores)
    assert output["available_component_weight"] == 82
    assert output["missing_component_weight"] == 18
    assert output["score_completeness_pct"] == 82.0
    assert output["acquisition_score"] == 0.0
    assert json.loads(output["missing_score_components"]) == ["client_fit_score"]
    assert output["score_completeness_review_flag"] is False

    scores["aum_fit_score"] = None
    output = calculate_acquisition_score(scores)
    assert output["available_component_weight"] == 62
    assert output["missing_component_weight"] == 38
    assert output["score_completeness_review_flag"] is True


def test_exact_30_percent_boundary():
    scores = full_scores(1)
    scores["aum_fit_score"] = None  # 20 missing
    scores["account_practice_fit_score"] = None  # +14 = 34, over boundary
    over = calculate_acquisition_score(scores)
    assert over["missing_component_weight"] == 34
    assert over["score_completeness_review_flag"] is True

    scores = full_scores(1)
    scores["aum_fit_score"] = None  # 20 missing
    scores["practice_complexity_score"] = None  # +10 = 30
    exact = calculate_acquisition_score(scores)
    assert exact["missing_component_weight"] == 30
    assert exact["score_completeness_review_flag"] is False


def test_review_propagation_and_hard_exclusion_precedence():
    review = calculate_acquisition_score(
        full_scores(1), eligibility_review_required=True, regulatory_review_flag=True
    )
    assert review["review_required"] is True
    assert review["regulatory_review_flag"] is True

    excluded = calculate_acquisition_score(
        full_scores(1), eligibility_status="EXCLUDED", hard_exclusion_reason="OUTSIDE_AUM_MANDATE",
        regulatory_review_flag=True,
    )
    assert excluded["acquisition_score"] is None
    assert excluded["review_required"] is False


def test_reasons_are_deduplicated_and_ordered():
    output = calculate_acquisition_score(
        full_scores(1),
        reason_lists={
            "eligibility": '["PREFERRED_AUM_BAND","SHARED"]',
            "client": '["SHARED","HNW_INDIVIDUAL_FOCUSED"]',
        },
    )
    assert json.loads(output["reason_codes"]) == [
        "PREFERRED_AUM_BAND",
        "SHARED",
        "HNW_INDIVIDUAL_FOCUSED",
    ]


def test_dataframe_evaluation_is_deterministic_and_preserves_components():
    row = {"firm_id": "1", "eligibility_status": "ELIGIBLE", "review_required": False}
    row.update(full_scores(1))
    row["reason_codes"] = '["TARGET_AUM_BAND"]'
    row["client_fit_reason_codes"] = '["INDIVIDUAL_CLIENT_FOCUSED"]'
    output = evaluate_acquisition_scores(pd.DataFrame([row]))
    assert output.loc[0, "acquisition_score"] == 7.0
    assert output.loc[0, "client_fit_score"] == 1
    assert json.loads(output.loc[0, "reason_codes"]) == [
        "TARGET_AUM_BAND",
        "INDIVIDUAL_CLIENT_FOCUSED",
    ]

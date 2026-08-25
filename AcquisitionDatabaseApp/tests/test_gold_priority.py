import json

import pandas as pd

from src.gold_priority import evaluate_priorities, assign_priority


def assign(score, readiness="PRIORITY_READY", review=False, status="ELIGIBLE", exclusion=None):
    return assign_priority(
        score,
        eligibility_status=status,
        priority_readiness=readiness,
        review_required=review,
        hard_exclusion_reason=exclusion,
    )


def test_priority_a_boundaries_and_readiness():
    assert assign(95)["priority_category"] == "PRIORITY_A"
    assert assign(92.5)["priority_category"] == "PRIORITY_A"
    assert assign(92.499999)["priority_category"] == "PRIORITY_B"
    assert assign(95, readiness="REVIEW_BEFORE_PRIORITY", review=True)["priority_category"] == "PRIORITY_B"


def test_priority_b_and_c_boundaries():
    assert assign(75)["priority_category"] == "PRIORITY_B"
    assert assign(74.999999)["priority_category"] == "PRIORITY_C"
    assert assign(0)["priority_category"] == "PRIORITY_C"
    assert "BELOW_PRIORITY_A_THRESHOLD" in json.loads(assign(75)["priority_reason_codes"])


def test_exclusion_precedence_and_null_scores():
    excluded = assign(100, status="EXCLUDED", exclusion="OUTSIDE_AUM_MANDATE")
    assert excluded["priority_category"] == "EXCLUDED"
    assert json.loads(excluded["priority_reason_codes"]) == ["OUTSIDE_AUM_MANDATE"]

    null_excluded = assign(None, status="EXCLUDED", exclusion="MISSING_CORE_DATA")
    assert null_excluded["priority_category"] == "EXCLUDED"
    assert assign(None)["priority_category"] == "PRIORITY_C"
    assert "MISSING_ACQUISITION_SCORE" in json.loads(assign(None)["priority_reason_codes"])


def test_review_overlay_is_not_erased():
    output = assign(90, readiness="REVIEW_BEFORE_PRIORITY", review=True)
    assert output["priority_category"] == "PRIORITY_B"


def test_dataframe_order_does_not_affect_classification():
    frame = pd.DataFrame(
        [
            {"firm_id": "a", "acquisition_score": 95, "eligibility_status": "ELIGIBLE", "priority_readiness": "PRIORITY_READY", "review_required": False},
            {"firm_id": "b", "acquisition_score": 75, "eligibility_status": "ELIGIBLE", "priority_readiness": "REVIEW_BEFORE_PRIORITY", "review_required": True},
        ]
    )
    forward = evaluate_priorities(frame).set_index("firm_id")["priority_category"].to_dict()
    reverse = evaluate_priorities(frame.iloc[::-1]).set_index("firm_id")["priority_category"].to_dict()
    assert forward == reverse == {"a": "PRIORITY_A", "b": "PRIORITY_B"}

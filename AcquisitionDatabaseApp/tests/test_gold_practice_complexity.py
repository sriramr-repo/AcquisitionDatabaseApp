import json

import pandas as pd

from src.gold_practice_complexity import (
    MAX_SCORE,
    calculate_practice_complexity,
    evaluate_practice_complexity,
)


CONTROL_FALSE = {
    "has_related_person_control": False,
    "under_common_control": False,
    "shares_supervised_persons": False,
    "shares_location": False,
    "has_unlisted_control_person": False,
}


def score(employee_count, advisory_employee_count, **controls):
    values = dict(CONTROL_FALSE)
    values.update(controls)
    return calculate_practice_complexity(employee_count, advisory_employee_count, **values)


def test_employee_size_boundaries():
    expected = {0: 5.0, 1: 5.0, 3: 5.0, 4: 4.0, 10: 4.0, 11: 2.0, 25: 2.0, 26: 0.0}
    for count, expected_score in expected.items():
        assert score(count, 0)["employee_size_score"] == expected_score


def test_advisory_team_boundaries():
    expected = {0: 3.0, 1: 3.0, 2: 2.0, 3: 2.0, 4: 1.0, 10: 1.0, 11: 0.0}
    for count, expected_score in expected.items():
        assert score(11, count)["advisory_team_score"] == expected_score


def test_simple_and_complex_control_structures():
    simple = score(3, 1)
    complex_control = score(3, 1, under_common_control=True)
    multiple = score(3, 1, shares_location=True, has_unlisted_control_person=True)

    assert simple["standalone_structure_score"] == 2.0
    assert "SIMPLE_CONTROL_STRUCTURE" in simple["practice_complexity_reason_codes"]
    assert complex_control["standalone_structure_score"] == 0.0
    assert multiple["standalone_structure_score"] == 0.0
    assert "COMPLEX_CONTROL_STRUCTURE" in complex_control["practice_complexity_reason_codes"]


def test_missing_control_and_staffing_data_remain_unavailable():
    missing_control = score(3, 1, shares_location=None)
    missing_employee = score(None, 1)
    missing_advisory = score(3, None)

    assert missing_control["standalone_structure_score"] is None
    assert missing_control["practice_complexity_score"] is None
    assert "MISSING_CONTROL_DATA" in missing_control["practice_complexity_reason_codes"]
    assert missing_employee["employee_size_score"] is None
    assert missing_advisory["advisory_team_score"] is None
    assert missing_employee["practice_complexity_score"] is None


def test_zero_employees_is_valid_but_flagged():
    output = score(0, 0)
    assert output["employee_size_score"] == 5.0
    assert output["advisory_team_score"] == 3.0
    assert output["practice_complexity_score"] == 10.0
    assert "ZERO_EMPLOYEE_COUNT_REVIEW" in output["practice_complexity_reason_codes"]


def test_invalid_staffing_relationships_are_unscored():
    for employees, advisory in [(-1, 0), (3, 4), (0, 1)]:
        output = score(employees, advisory)
        assert output["invalid_staffing_relationship"] is True
        assert output["practice_complexity_score"] is None
        assert "INVALID_STAFFING_RELATIONSHIP" in output["practice_complexity_reason_codes"]


def test_maximum_score_and_dataframe_interface():
    output = score(3, 1)
    assert output["practice_complexity_score"] == MAX_SCORE

    firms = pd.DataFrame(
        [{"firm_id": "1", "employee_count": 3, "advisory_employee_count": 1, **CONTROL_FALSE}]
    )
    evaluated = evaluate_practice_complexity(firms)
    assert evaluated.loc[0, "practice_complexity_score"] == 10.0
    assert json.loads(evaluated.loc[0, "practice_complexity_reason_codes"]) == [
        "SMALL_EMPLOYEE_BASE",
        "SMALL_ADVISORY_TEAM",
        "SIMPLE_CONTROL_STRUCTURE",
    ]

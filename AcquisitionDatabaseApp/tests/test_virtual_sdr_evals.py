from pathlib import Path

from src.virtual_sdr_evals import evaluate_case, load_evaluation_cases


def test_virtual_sdr_evaluation_dataset_matches_expected_contracts():
    cases = load_evaluation_cases(Path("tests/fixtures/virtual_sdr_eval_cases.json"))
    results = [evaluate_case(case) for case in cases]
    assert len(results) == 2
    assert all(result["passed"] for result in results)
    assert {result["actual_status"] for result in results} == {"PASSED", "FAILED"}

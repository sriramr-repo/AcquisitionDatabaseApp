import pytest

from src.dashboard_publisher import _dataset_date, _firm_universe_counts, _source_score_version
from src.gold_eligibility import SCORE_VERSION


def test_publisher_uses_score_version_from_gold():
    assert _source_score_version(
        ["firm_id", "score_version"],
        [("1", "SCM_ACQUISITION_V1"), ("2", "SCM_ACQUISITION_V1")],
    ) == "SCM_ACQUISITION_V1"


def test_publisher_defaults_to_current_version_when_source_field_is_absent():
    assert _source_score_version(["firm_id"], [("1",)]) == SCORE_VERSION


def test_publisher_rejects_mixed_score_versions():
    with pytest.raises(RuntimeError, match="mixed score versions"):
        _source_score_version(
            ["firm_id", "score_version"],
            [("1", "SCM_ACQUISITION_V1"), ("2", "SCM_ACQUISITION_V2")],
        )


def test_iapd_dataset_date_and_universe_counts_are_separate():
    columns = ["firm_id", "is_registered", "is_era_only", "is_dual_registered", "priority_category"]
    rows = [
        ("1", True, False, False, "PRIORITY_A"),
        ("2", True, False, True, "EXCLUDED"),
        ("3", False, True, False, "EXCLUDED"),
    ]
    assert _dataset_date("iapdfirm20261107") == "2026-11-07"
    assert _firm_universe_counts(columns, rows) == {
        "source_firm_count": 3,
        "registered_firm_count": 2,
        "era_only_firm_count": 1,
        "dual_registered_firm_count": 1,
        "acquisition_target_count": 1,
    }


def test_historical_dataset_does_not_infer_registration_counts():
    assert _firm_universe_counts(["firm_id", "priority_category"], [("1", "PRIORITY_A")]) == {
        "source_firm_count": 1,
        "registered_firm_count": None,
        "era_only_firm_count": None,
        "dual_registered_firm_count": None,
        "acquisition_target_count": None,
    }

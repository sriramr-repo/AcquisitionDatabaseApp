import pytest

from src.dashboard_publisher import _source_score_version
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

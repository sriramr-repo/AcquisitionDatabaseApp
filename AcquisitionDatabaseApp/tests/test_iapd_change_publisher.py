import json

import pytest

from src.iapd_change_publisher import IAPDChangePublishError, publish_change_report, validate_change_report
from src.iapd_batch import _bundle_manifest_counts


def report():
    names = ("new_representatives", "disappeared_representatives", "employer_changes", "registration_changes", "disclosure_changes", "material_contact_changes")
    counts = {name: 0 for name in names}
    counts.update(new_representatives=1, employer_changes=1)
    return {
        "comparison_id": "a" * 64, "status": "success",
        "current": {"snapshot_id": "current", "dataset_version": "v1", "snapshot_date": "2026-09-08"},
        "previous": {"snapshot_id": "previous", "dataset_version": "v1", "snapshot_date": "2026-08-20"},
        "counts": counts,
        "firm_changes": [{"firm_id": "10", "counts": dict(counts), "representative_samples": {"new_representatives": ["100"]}}],
        "affected_firm_count": 1,
        "interpretation_guardrails": ["Absence does not establish termination.", "A disclosure change does not establish misconduct.", "No event establishes seller intent."],
    }


def test_change_report_validates_and_dry_run_never_connects(tmp_path):
    path = tmp_path / "comparison.json"
    path.write_text(json.dumps(report()))
    result = publish_change_report(report_path=path, database_url="", dry_run=True)
    assert result["status"] == "validated"
    assert result["publish_candidates"] == result["national_affected_firms"] == 1


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(comparison_id="bad"),
    lambda value: value["counts"].update(new_representatives=-1),
    lambda value: value.update(affected_firm_count=2),
    lambda value: value.update(interpretation_guardrails=[]),
])
def test_change_report_fails_closed_on_invalid_contract(mutation):
    value = report()
    mutation(value)
    with pytest.raises(IAPDChangePublishError):
        validate_change_report(value)


def test_bundle_manifest_counts_preserve_zero_and_required_fields(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps({"dataset_version": "v1", "firm_count": 3, "available_bundle_count": 2, "unavailable_bundle_count": 1, "representative_count": 0}))
    assert _bundle_manifest_counts(path)["representative_count"] == 0


def test_bundle_manifest_counts_rejects_incomplete_document(tmp_path):
    path = tmp_path / "manifest.json"
    path.write_text("{}")
    with pytest.raises(ValueError, match="required aggregate"):
        _bundle_manifest_counts(path)

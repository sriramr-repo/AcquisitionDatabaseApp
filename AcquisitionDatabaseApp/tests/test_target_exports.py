import json

import duckdb
import pandas as pd

from src.gold_v1 import GOLD_V1_COLUMNS, gold_v1_table_name
from src.target_exports import EXPORT_COLUMNS, EXPORT_SCHEMA_VERSION, export_priority_targets


def _gold_fixture():
    rows = [
        {
            "firm_id": "a2", "name": "A Two", "primary_business_name": "A Two",
            "total_aum": 42_300_000.0, "discretionary_aum": 40_608_000.0,
            "total_account_count": 100, "individual_hnw_client_aum": 37_224_000.0,
            "employee_count": 3, "advisory_employee_count": 2,
            "organization_type": "LLC", "provides_financial_planning": True,
            "has_item_11_disclosure": False, "score_version": "SCM_ACQUISITION_V1",
            "acquisition_score": 95.4, "priority_category": "PRIORITY_A",
            "priority_readiness": "PRIORITY_READY", "review_required": False,
            "regulatory_review_flag": False, "score_completeness_pct": 100.0,
            "client_fit_score": 18.0, "reason_codes": '["PREFERRED_AUM_BAND"]',
            "priority_reason_codes": '["HIGH_SCORE_PRIORITY_READY"]',
        },
        {
            "firm_id": "a1", "name": "A One", "primary_business_name": "A One",
            "total_aum": 30_000_000.0, "acquisition_score": 95.4,
            "score_version": "SCM_ACQUISITION_V1", "priority_category": "PRIORITY_A",
            "priority_readiness": "PRIORITY_READY", "review_required": False,
            "regulatory_review_flag": False, "score_completeness_pct": 100.0,
            "client_fit_score": 18.0, "priority_reason_codes": '["HIGH_SCORE_PRIORITY_READY"]',
        },
        {
            "firm_id": "b2", "name": "B Review", "primary_business_name": "B Review",
            "total_aum": 50_000_000.0, "acquisition_score": 85.0,
            "score_version": "SCM_ACQUISITION_V1", "priority_category": "PRIORITY_B",
            "priority_readiness": "REVIEW_BEFORE_PRIORITY", "review_required": True,
            "regulatory_review_flag": True, "score_completeness_pct": 82.0,
            "client_fit_score": None,
            "priority_readiness_reason_codes": '["MISSING_MATERIAL_CLIENT_DATA","REGULATORY_REVIEW_REQUIRED"]',
        },
        {
            "firm_id": "b1", "name": "B Ready", "primary_business_name": "B Ready",
            "total_aum": 25_000_000.0, "acquisition_score": 80.0,
            "score_version": "SCM_ACQUISITION_V1", "priority_category": "PRIORITY_B",
            "priority_readiness": "PRIORITY_READY", "review_required": False,
            "regulatory_review_flag": False, "score_completeness_pct": 100.0,
            "client_fit_score": 16.0,
        },
    ]
    frame = pd.DataFrame(rows)
    for column in GOLD_V1_COLUMNS:
        if column not in frame:
            frame[column] = None
    return frame.loc[:, list(GOLD_V1_COLUMNS)]


def _source_db(tmp_path):
    connection = duckdb.connect(str(tmp_path / "source.duckdb"))
    connection.register("fixture", _gold_fixture())
    connection.execute(f'CREATE TABLE "{gold_v1_table_name("fixture")}" AS SELECT * FROM fixture')
    connection.execute("CREATE TABLE gold_firms_legacy AS SELECT 'legacy' AS firm_id")
    connection.unregister("fixture")
    return connection


def test_exports_filter_counts_schema_and_blank_research_fields(tmp_path):
    connection = _source_db(tmp_path)
    paths = export_priority_targets("fixture", tmp_path / "exports", connection=connection)
    a = pd.read_csv(paths["priority_a_csv"], keep_default_na=False)
    b = pd.read_csv(paths["priority_b_csv"], keep_default_na=False)
    review = pd.read_csv(paths["priority_b_review_csv"], keep_default_na=False)
    assert len(a) == 2
    assert len(b) == 2
    assert len(review) == 1
    assert list(a.columns) == list(EXPORT_COLUMNS)
    assert set(a["research_status"]) == {""}
    assert set(a["founder_name"]) == {""}
    assert set(a["priority_category"]) == {"PRIORITY_A"}
    assert set(b["priority_category"]) == {"PRIORITY_B"}
    assert set(review["priority_category"]) == {"PRIORITY_B"}
    assert set(review["review_required"]) == {True}
    assert "Missing client-mix data" in review.loc[0, "review_reason_summary"]
    assert "Regulatory review required" in review.loc[0, "review_reason_summary"]
    connection.close()


def test_summary_omits_missing_values_and_uses_structured_facts(tmp_path):
    connection = _source_db(tmp_path)
    paths = export_priority_targets("fixture", tmp_path / "exports", connection=connection)
    a = pd.read_csv(paths["priority_a_csv"], keep_default_na=False).set_index("firm_id")
    assert a.loc["a2", "screening_summary"] == (
        "$42.3M AUM; 96% discretionary; 88% individual/HNW AUM; "
        "3 employees; 2 advisory employees; financial-planning model; "
        "no Item 11 disclosure; acquisition score 95.4."
    )
    assert "employees" not in a.loc["a1", "screening_summary"]
    assert "discretionary" not in a.loc["a1", "screening_summary"]
    assert "founder" not in a.loc["a1", "screening_summary"].lower()
    connection.close()


def test_sorting_is_deterministic_and_legacy_table_is_not_used(tmp_path):
    connection = _source_db(tmp_path)
    paths = export_priority_targets("fixture", tmp_path / "exports", connection=connection)
    a = pd.read_csv(paths["priority_a_csv"], keep_default_na=False)
    b = pd.read_csv(paths["priority_b_csv"], keep_default_na=False)
    assert list(a["firm_id"]) == ["a1", "a2"]  # score tie, then AUM ascending
    assert list(b["firm_id"]) == ["b1", "b2"]  # review false before true
    assert connection.execute("SELECT * FROM gold_firms_legacy").fetchall() == [("legacy",)]
    connection.close()


def test_manifest_and_duplicate_prevention(tmp_path):
    connection = _source_db(tmp_path)
    paths = export_priority_targets("fixture", tmp_path / "exports", connection=connection)
    manifest = json.loads(paths["manifest"].read_text())
    assert manifest["export_schema_version"] == EXPORT_SCHEMA_VERSION
    assert manifest["gold_v1_source_table"] == gold_v1_table_name("fixture")
    assert manifest["priority_a_count"] == 2
    assert manifest["priority_b_count"] == 2
    assert manifest["priority_b_review_count"] == 1
    assert manifest["output_filenames"]["priority_a_csv"] == "priority_a_targets.csv"

    duplicate = _gold_fixture().iloc[[0]].copy()
    duplicate = pd.concat([duplicate, duplicate], ignore_index=True)
    connection.execute(f'DROP TABLE "{gold_v1_table_name("fixture")}"')
    connection.register("duplicate_fixture", duplicate)
    connection.execute(f'CREATE TABLE "{gold_v1_table_name("fixture")}" AS SELECT * FROM duplicate_fixture')
    connection.unregister("duplicate_fixture")
    try:
        export_priority_targets("fixture", tmp_path / "duplicate", connection=connection)
    except ValueError as exc:
        assert "unique firm_id" in str(exc)
    else:
        raise AssertionError("duplicate firm_id was accepted")
    connection.close()

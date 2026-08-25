import hashlib

import duckdb
import pandas as pd

import src.gold_v1 as gold_v1
from src.gold_v1 import GOLD_V1_COLUMNS, GoldV1Builder, gold_v1_table_name


def _scored_frame():
    return pd.DataFrame(
        [
            {
                "firm_id": "excluded",
                "total_aum": 10.0,
                "eligibility_status": "EXCLUDED",
                "hard_exclusion_reason": "OUTSIDE_AUM_MANDATE",
                "acquisition_score": None,
            },
            {
                "firm_id": "a",
                "total_aum": 30_000_000.0,
                "eligibility_status": "ELIGIBLE",
                "hard_exclusion_reason": None,
                "acquisition_score": 95.0,
                "priority_readiness": "PRIORITY_READY",
                "priority_ready": True,
                "review_required": False,
                "client_fit_score": 18.0,
                "aum_fit_score": 20.0,
                "discretionary_fit_score": 18.0,
                "account_practice_fit_score": 14.0,
                "regulatory_quality_score": 10.0,
                "score_completeness_pct": 100.0,
                "regulatory_review_flag": False,
                "invalid_discretionary_aum_relationship": False,
                "invalid_client_aum_relationship": False,
                "invalid_account_relationship": False,
            },
            {
                "firm_id": "b",
                "total_aum": 40_000_000.0,
                "eligibility_status": "ELIGIBLE",
                "hard_exclusion_reason": None,
                "acquisition_score": 80.0,
                "priority_readiness": "REVIEW_BEFORE_PRIORITY",
                "priority_ready": False,
                "review_required": True,
            },
            {
                "firm_id": "c",
                "total_aum": 50_000_000.0,
                "eligibility_status": "ELIGIBLE",
                "hard_exclusion_reason": None,
                "acquisition_score": 50.0,
                "priority_readiness": "PRIORITY_READY",
                "priority_ready": True,
                "review_required": False,
            },
        ]
    )


def _complete_frame():
    result = _scored_frame()
    for column in GOLD_V1_COLUMNS:
        if column not in result:
            result[column] = None
    return result.loc[:, list(GOLD_V1_COLUMNS)]


def test_builder_calls_existing_stack_and_preserves_deterministic_order(monkeypatch):
    calls = []
    source = pd.DataFrame({"firm_id": ["one"], "total_aum": [30_000_000.0]})
    scored = _scored_frame().iloc[[1]].copy()

    def score(frame, *, run_components):
        calls.append(("score", run_components))
        return scored.copy()

    def readiness(frame):
        calls.append(("readiness",))
        return frame.assign(priority_readiness="PRIORITY_READY", priority_ready=True)

    def priority(frame):
        calls.append(("priority",))
        return frame.assign(priority_category="PRIORITY_A", priority_reason_codes='["HIGH_SCORE_PRIORITY_READY"]')

    monkeypatch.setattr(gold_v1, "evaluate_acquisition_scores", score)
    monkeypatch.setattr(gold_v1, "evaluate_priority_readiness", readiness)
    monkeypatch.setattr(gold_v1, "evaluate_priorities", priority)

    output = GoldV1Builder().build(source)
    assert calls == [("score", True), ("readiness",), ("priority",)]
    assert list(output.columns) == list(GOLD_V1_COLUMNS)
    assert output.loc[0, "priority_category"] == "PRIORITY_A"


def test_fixture_distribution_and_excluded_score_null():
    scored = _scored_frame()
    output = GoldV1Builder()._select_columns(
        gold_v1.evaluate_priorities(gold_v1.evaluate_priority_readiness(scored))
    )
    assert output.priority_category.value_counts().to_dict() == {
        "EXCLUDED": 1,
        "PRIORITY_A": 1,
        "PRIORITY_B": 1,
        "PRIORITY_C": 1,
    }
    assert pd.isna(output.loc[output.firm_id == "excluded", "acquisition_score"]).all()


def test_priority_a_integrity_and_duplicate_rejection():
    scored = _scored_frame()
    output = GoldV1Builder()._select_columns(
        gold_v1.evaluate_priorities(gold_v1.evaluate_priority_readiness(scored))
    )
    row = output.loc[output.priority_category == "PRIORITY_A"].iloc[0]
    assert row.acquisition_score >= 92.5
    assert row.priority_readiness == "PRIORITY_READY"
    assert row.review_required is False or not bool(row.review_required)
    assert row.client_fit_score is not None
    assert row.score_completeness_pct >= 90
    assert row.regulatory_review_flag is False or not bool(row.regulatory_review_flag)

    duplicate = pd.concat([_scored_frame(), _scored_frame().iloc[[0]]], ignore_index=True)
    try:
        GoldV1Builder()._select_columns(duplicate)
    except ValueError as exc:
        assert "unique firm_id" in str(exc)
    else:
        raise AssertionError("duplicate firm_id was accepted")


def test_duckdb_and_parquet_write_without_touching_legacy(tmp_path):
    builder = GoldV1Builder()
    frame = _complete_frame()
    db_path = tmp_path / "analytics.duckdb"
    parquet_path = tmp_path / "gold" / "gold_scm_acquisition_v1_test.parquet"
    connection = duckdb.connect(str(db_path))
    connection.execute("CREATE TABLE gold_firms_test AS SELECT 1 AS sentinel")
    before = connection.execute("SELECT * FROM gold_firms_test").fetchall()

    builder.write_duckdb(frame, connection, gold_v1_table_name("test"))
    builder.write_parquet(frame, parquet_path)

    table_rows = connection.execute(
        f'SELECT * FROM "{gold_v1_table_name("test")}" ORDER BY firm_id'
    ).fetchdf()
    parquet_rows = connection.execute(
        "SELECT * FROM read_parquet(?) ORDER BY firm_id", [str(parquet_path)]
    ).fetchdf()
    assert len(table_rows) == len(parquet_rows) == 4
    assert list(table_rows.columns) == list(parquet_rows.columns) == list(GOLD_V1_COLUMNS)
    assert table_rows.priority_category.value_counts().to_dict() == parquet_rows.priority_category.value_counts().to_dict()
    assert connection.execute("SELECT * FROM gold_firms_test").fetchall() == before
    assert parquet_path.stat().st_size > 0
    assert hashlib.sha256(parquet_path.read_bytes()).hexdigest()
    connection.close()

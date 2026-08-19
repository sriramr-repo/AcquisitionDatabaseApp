import sqlite3

import duckdb
import pytest

from src.gold_v1 import gold_v1_table_name
from src.research import (
    ASSESSMENT_LEVELS,
    CONFIDENCE_LEVELS,
    RESEARCH_STATUSES,
    ResearchRepository,
)


def test_create_get_update_research_record(tmp_path):
    repository = ResearchRepository(tmp_path / "research.db")
    created = repository.create_research_record("firm-1", "ia-test")
    assert created["research_status"] == "NOT_STARTED"
    assert created["founder_name"] is None
    assert repository.get_research_record("firm-1", "ia-test")["firm_id"] == "firm-1"

    updated = repository.update_research_record(
        "firm-1", "ia-test", research_status="IN_PROGRESS", founder_name="Example Founder"
    )
    assert updated["research_status"] == "IN_PROGRESS"
    assert updated["founder_name"] == "Example Founder"
    with pytest.raises(ValueError, match="already exists"):
        repository.create_research_record("firm-1", "ia-test")


def test_status_confidence_and_assessment_validation(tmp_path):
    repository = ResearchRepository(tmp_path / "research.db")
    with pytest.raises(ValueError):
        repository.create_research_record("firm", "v1", research_status="DONE")
    with pytest.raises(ValueError):
        repository.create_research_record("firm", "v1", founder_age_confidence="MAYBE")
    with pytest.raises(ValueError):
        repository.create_research_record("firm", "v1", succession_readiness_assessment="MAYBE")
    assert "NOT_STARTED" in RESEARCH_STATUSES
    assert "VERIFIED" in CONFIDENCE_LEVELS
    assert "UNKNOWN" in ASSESSMENT_LEVELS


def test_estimates_and_timestamps_validation(tmp_path):
    repository = ResearchRepository(tmp_path / "research.db")
    with pytest.raises(ValueError):
        repository.create_research_record("firm", "v1", estimated_revenue=-1)
    with pytest.raises(ValueError):
        repository.create_research_record(
            "firm", "v1", estimated_valuation_low=20, estimated_valuation_high=10
        )
    with pytest.raises(ValueError):
        repository.create_research_record("firm", "v1", research_started_at="not-a-time")
    record = repository.create_research_record(
        "firm", "v1", estimated_valuation_low=10, estimated_valuation_high=20,
        research_started_at="2026-08-17T00:00:00Z",
    )
    assert record["estimated_valuation_low"] == 10


def test_sources_and_foreign_key_integrity(tmp_path):
    repository = ResearchRepository(tmp_path / "research.db")
    with pytest.raises(ValueError, match="existing research record"):
        repository.add_research_source(
            "firm", "v1", source_type="company_website", field_supported="founder_name"
        )
    repository.create_research_record("firm", "v1")
    source_id = repository.add_research_source(
        "firm", "v1", source_type="company_website", source_url="https://example.com",
        source_title="About", accessed_at="2026-08-17T00:00:00Z", field_supported="founder_name",
    )
    sources = repository.list_research_sources("firm", "v1")
    assert sources[0]["source_id"] == source_id
    assert sources[0]["field_supported"] == "founder_name"


def test_factual_fields_require_linked_evidence(tmp_path):
    repository = ResearchRepository(tmp_path / "research.db")
    repository.create_research_record("firm", "v1")
    with pytest.raises(ValueError, match="evidence source"):
        repository.update_factual_fields(
            "firm", "v1", source_ids=[], founder_role="Principal"
        )
    source_id = repository.add_research_source(
        "firm", "v1", source_type="sec_record", source_title="SEC",
        field_supported="founder_role",
    )
    updated = repository.update_factual_fields(
        "firm", "v1", source_ids=[source_id], founder_role="Principal"
    )
    assert updated["founder_role"] == "Principal"


def _gold_connection(tmp_path):
    connection = duckdb.connect(str(tmp_path / "analytics.duckdb"))
    connection.execute(
        f'''CREATE TABLE "{gold_v1_table_name("v1")}" AS
        SELECT * FROM (VALUES
            ('a', 'PRIORITY_A'), ('b', 'PRIORITY_A'), ('c', 'PRIORITY_B')
        ) AS firms(firm_id, priority_category)'''
    )
    return connection


def test_priority_a_initialization_is_idempotent_and_non_destructive(tmp_path):
    repository = ResearchRepository(tmp_path / "research.db")
    connection = _gold_connection(tmp_path)
    first = repository.initialize_priority_a("v1", connection=connection)
    assert first == {"created": 2, "existing": 0, "total": 2}
    repository.update_research_record("a", "v1", research_status="IN_PROGRESS", founder_name="Analyst Entry")
    second = repository.initialize_priority_a("v1", connection=connection)
    assert second == {"created": 0, "existing": 2, "total": 2}
    rows = repository.get_research_record("a", "v1")
    assert rows["research_status"] == "IN_PROGRESS"
    assert rows["founder_name"] == "Analyst Entry"
    assert connection.execute(
        f'SELECT COUNT(*) FROM "{gold_v1_table_name("v1")}"'
    ).fetchone()[0] == 3
    connection.close()


def test_all_firm_source_initialization_is_idempotent(tmp_path):
    repository = ResearchRepository(tmp_path / "research.db")
    connection = duckdb.connect(str(tmp_path / "analytics.duckdb"))
    connection.execute(
        f'''CREATE TABLE "{gold_v1_table_name("v1")}" AS
        SELECT * FROM (VALUES
            ('a', 'EXCLUDED', 'NY', NULL), ('b', 'PRIORITY_A', 'CT', 'https://b.example'),
            ('c', 'PRIORITY_B', 'MA', NULL), ('d', 'PRIORITY_C', 'RI', 'https://d.example')
        ) AS firms(firm_id, priority_category, organization_state, website_address)'''
    )
    connection.close()
    first = repository.initialize_source_tasks(
        "v1", duckdb_path=tmp_path / "analytics.duckdb", source_types=("iapd",),
        priority_categories=("EXCLUDED", "PRIORITY_A", "PRIORITY_B", "PRIORITY_C"),
    )
    second = repository.initialize_source_tasks(
        "v1", duckdb_path=tmp_path / "analytics.duckdb", source_types=("iapd",),
        priority_categories=("EXCLUDED", "PRIORITY_A", "PRIORITY_B", "PRIORITY_C"),
    )
    assert first == {"target_count": 4, "targets_created": 4, "tasks_created": 4, "total_tasks": 4}
    assert second == {"target_count": 4, "targets_created": 0, "tasks_created": 0, "total_tasks": 4}
    assert repository.source_coverage("v1")["target_count"] == 4


def test_duplicate_research_record_is_rejected_by_sqlite_key(tmp_path):
    repository = ResearchRepository(tmp_path / "research.db")
    repository.create_research_record("firm", "v1")
    with sqlite3.connect(tmp_path / "research.db") as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM target_research WHERE firm_id='firm' AND dataset_version='v1'"
        ).fetchone()[0] == 1

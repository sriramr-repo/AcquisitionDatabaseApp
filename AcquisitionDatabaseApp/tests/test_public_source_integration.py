import duckdb
import pandas as pd

from src.gold_v1 import gold_v1_table_name
from src.historical_adv import parse_historical_adv_csv, register_historical_adv_csv
from src.research import ResearchRepository
from src.source_registry import FORM_ADV_FIELD_DEFINITIONS


def test_source_taxonomy_and_adv_definition_registry():
    assert FORM_ADV_FIELD_DEFINITIONS["total_aum"]["item"] == "Item 5.F(2)(c)"
    assert FORM_ADV_FIELD_DEFINITIONS["employee_count"]["item"] == "Item 5.A"
    assert FORM_ADV_FIELD_DEFINITIONS["advisory_employee_count"]["item"] == "Item 5.B(1)"


def test_priority_a_and_b_source_tasks_are_idempotent(tmp_path):
    db_path = tmp_path / "research.db"
    analytics = duckdb.connect(str(tmp_path / "analytics.duckdb"))
    analytics.execute(
        f'''CREATE TABLE "{gold_v1_table_name("v1")}" AS SELECT * FROM (VALUES
        ('a', 'MA', 'https://a.example', 'PRIORITY_A'),
        ('b', 'CT', NULL, 'PRIORITY_B'),
        ('c', 'NY', NULL, 'EXCLUDED')
        ) AS t(firm_id, organization_state, website_address, priority_category)'''
    )
    analytics.close()
    repository = ResearchRepository(db_path)
    result = repository.initialize_source_tasks("v1", duckdb_path=tmp_path / "analytics.duckdb")
    assert result["target_count"] == 2
    assert result["tasks_created"] == 18
    assert len(repository.list_source_tasks(dataset_version="v1")) == 18
    second = repository.initialize_source_tasks("v1", duckdb_path=tmp_path / "analytics.duckdb")
    assert second["tasks_created"] == 0
    assert repository.get_research_record("b", "v1")["research_status"] == "NOT_STARTED"


def test_observations_require_source_and_review_without_mutating_facts(tmp_path):
    repository = ResearchRepository(tmp_path / "research.db")
    repository.create_research_record("firm", "v1")
    source_id = repository.add_research_source(
        "firm", "v1", source_type="official_website", source_url="https://firm.example",
        field_supported="founder_name", source_authority="Firm", retrieval_status="REVIEW_REQUIRED",
    )
    observation_id = repository.add_observation(
        firm_id="firm", dataset_version="v1", source_id=source_id,
        canonical_field="founder_name", proposed_value="A. Founder", confidence="HIGH",
    )
    reviewed = repository.review_observation(observation_id, review_status="ACCEPTED", reviewer="analyst")
    assert reviewed["review_status"] == "ACCEPTED"
    assert repository.get_research_record("firm", "v1")["founder_name"] is None


def test_historical_adv_csv_registration_is_metadata_only(tmp_path):
    csv_path = tmp_path / "historical.csv"
    pd.DataFrame(
        [{"Organization CRD#": "123", "Latest ADV Filing Date": "2025-12-31", "Form Version": "1A"}]
    ).to_csv(csv_path, index=False)
    frame = parse_historical_adv_csv(csv_path)
    assert frame.loc[0, "firm_id"] == "123"
    repository = ResearchRepository(tmp_path / "research.db")
    assert register_historical_adv_csv(csv_path, repository) == 1
    with repository._connect() as connection:
        row = connection.execute("SELECT firm_id, filing_date FROM historical_adv_filings").fetchone()
    assert tuple(row) == ("123", "2025-12-31")

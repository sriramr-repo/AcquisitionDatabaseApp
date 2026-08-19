import duckdb

from src.dossiers import dossier_filename, generate_target_dossier
from src.gold_v1 import gold_v1_table_name
from src.research import ResearchRepository


def test_dossier_generation_is_deterministic_and_labels_categories(tmp_path):
    repository = ResearchRepository(tmp_path / "research.db")
    repository.create_research_record(
        "firm-1", "v1", research_status="RESEARCH_COMPLETE",
        founder_role="Principal", succession_readiness_assessment="UNKNOWN",
        estimated_revenue=100, revenue_estimation_method="AUM times fee rate",
        economics_confidence="MEDIUM", strategic_fit_assessment="MEDIUM",
        strategic_fit_notes="Assessment based on structured facts.",
    )
    repository.add_research_source(
        "firm-1", "v1", source_type="official_website", source_url="https://example.com",
        source_title="Firm site", accessed_at="2026-08-17T00:00:00Z",
        field_supported="founder_role",
    )
    connection = duckdb.connect(str(tmp_path / "analytics.duckdb"))
    connection.execute(
        f'''CREATE TABLE "{gold_v1_table_name("v1")}" AS SELECT * FROM (VALUES
        ('firm-1', 'Example Firm', 50000000.0, 50000000.0, 95.0, 'PRIORITY_A',
         'PRIORITY_READY', 1.0, 1.0, 1.0, 1.0, 0.0, '[]', 0.0)
        ) AS t(firm_id, name, total_aum, discretionary_aum, acquisition_score,
        priority_category, priority_readiness, employee_count, advisory_employee_count,
        provides_financial_planning, has_item_11_disclosure, regulatory_review_flag,
        reason_codes, review_required)'''
    )
    connection.close()
    path = generate_target_dossier(
        "firm-1", "v1", research_repository=repository,
        duckdb_path=tmp_path / "analytics.duckdb", output_dir=tmp_path / "dossiers", draft=True,
    )
    assert path.name == dossier_filename("firm-1", "Example Firm")
    text = path.read_text()
    assert "SEC-derived facts" in text
    assert "Analyst assessment" in text
    assert "Estimate" in text
    assert "Analyst Review Required" in text
    assert "https://example.com" in text
    assert "AUM times fee rate" in text
    assert "Example Firm" in text

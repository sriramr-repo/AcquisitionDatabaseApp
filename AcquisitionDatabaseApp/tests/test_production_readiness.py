import json

import duckdb
import pytest

from src.change_intelligence import compare_gold_versions
from src.config import PROJECT_ROOT, Settings, settings
from src.research_queue import build_research_refresh_queue


def test_dev_settings_are_not_production_root():
    dev = Settings(ENVIRONMENT="DEV", DATA_ROOT=PROJECT_ROOT / "data-test-fixture")
    assert dev.BASE_DIR != (PROJECT_ROOT / "data").resolve()
    with pytest.raises(RuntimeError):
        dev.assert_safe_path(PROJECT_ROOT / "data" / "metadata.db")


def test_change_intelligence_emits_priority_and_aum_events(monkeypatch, tmp_path):
    db = tmp_path / "analytics.duckdb"
    connection = duckdb.connect(str(db))
    schema = """(firm_id VARCHAR, name VARCHAR, total_aum DOUBLE, discretionary_aum DOUBLE,
        total_account_count INTEGER, employee_count INTEGER, advisory_employee_count INTEGER,
        priority_category VARCHAR, has_item_11_disclosure BOOLEAN, registration_status VARCHAR)"""
    connection.execute(f"CREATE TABLE gold_scm_acquisition_v1_old {schema}")
    connection.execute(f"CREATE TABLE gold_scm_acquisition_v1_new {schema}")
    connection.execute("INSERT INTO gold_scm_acquisition_v1_old VALUES ('1','Firm',10000000,9000000,10,2,1,'PRIORITY_B',false,'active')")
    connection.execute("INSERT INTO gold_scm_acquisition_v1_new VALUES ('1','Firm',25000000,24000000,10,3,2,'PRIORITY_A',true,'active')")
    connection.close()
    monkeypatch.setattr(settings, "DUCKDB_FILE", db)
    report = compare_gold_versions("old", "new")
    events = {event["event_type"] for event in report["events"]}
    assert {"PRIORITY_B_TO_A", "ENTERED_TARGET_AUM_BAND", "NEW_REGULATORY_DISCLOSURE", "MATERIAL_STAFFING_CHANGE"} <= events


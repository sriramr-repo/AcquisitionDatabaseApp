import duckdb
import pandas as pd

from src.change_intelligence import compare_gold_versions
from src.gold_v1 import gold_v1_table_name


def test_registration_transitions_and_era_relationship_changes_are_explicit(tmp_path):
    old = pd.DataFrame([
        {"firm_id": "1", "name": "One", "is_sec_registered": True, "is_state_registered": False,
         "has_era_relationship": False, "priority_category": "PRIORITY_C"},
        {"firm_id": "removed", "name": "Removed", "is_sec_registered": True, "is_state_registered": False,
         "has_era_relationship": False, "priority_category": "EXCLUDED"},
    ])
    new = pd.DataFrame([
        {"firm_id": "1", "name": "One", "is_sec_registered": False, "is_state_registered": True,
         "has_era_relationship": True, "priority_category": "PRIORITY_C"},
        {"firm_id": "new", "name": "New", "is_sec_registered": False, "is_state_registered": True,
         "has_era_relationship": False, "priority_category": "PRIORITY_C"},
    ])
    database = tmp_path / "analytics.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.register("old_frame", old)
        connection.register("new_frame", new)
        connection.execute(f'create table "{gold_v1_table_name("old")}" as select * from old_frame')
        connection.execute(f'create table "{gold_v1_table_name("new")}" as select * from new_frame')
    report = compare_gold_versions("old", "new", duckdb_path=database)
    events = {(item["event_type"], item["firm_id"]) for item in report["events"]}
    assert ("NEW_FIRM", "new") in events
    assert ("REMOVED_FIRM", "removed") in events
    assert ("REGISTRATION_TRANSITION", "1") in events
    assert ("ADDED_ERA_RELATIONSHIP", "1") in events

import zipfile
from pathlib import Path

import duckdb
import pytest

from src.gold_v1 import gold_v1_table_name
from src.staged_refresh import StagedRefresh
from src.storage import DatasetRegistry


DATASET = "ia07012026"


def _fixture_frames(tmp_path):
    """Copy a preserved local Gold V1 snapshot into memory; never write it."""
    production_db = Path(__file__).parents[1] / "data" / "analytics.duckdb"
    connection = duckdb.connect(str(production_db), read_only=True)
    try:
        source = connection.execute(f'SELECT * FROM "{gold_v1_table_name(DATASET)}"').df()
    finally:
        connection.close()
    # Keep both a Priority A and a non-A candidate so queue behavior is real.
    baseline = source[source["priority_category"].isin(["PRIORITY_A", "PRIORITY_B"])].head(8).copy()
    assert len(baseline) >= 3
    # Keep the change-intelligence fixture deterministic as the production
    # priority population evolves.
    baseline.loc[baseline.index[1], "has_item_11_disclosure"] = 0.0
    new = baseline.iloc[:-1].copy()
    new["has_item_11_disclosure"] = new["has_item_11_disclosure"].astype(object)
    added = baseline.iloc[[0]].copy()
    added["has_item_11_disclosure"] = added["has_item_11_disclosure"].astype(object)
    added["firm_id"] = "clean-room-new-firm"
    added["name"] = "CLEAN ROOM NEW FIRM"
    added["total_aum"] = added["total_aum"] * 1.25
    added["employee_count"] = added["employee_count"].fillna(1) + 1
    added["has_item_11_disclosure"] = True
    new = __import__("pandas").concat([new, added], ignore_index=True)
    changed = new["firm_id"] == baseline.iloc[1]["firm_id"]
    new.loc[changed, "total_aum"] = new.loc[changed, "total_aum"] * 1.30
    new.loc[changed, "employee_count"] = new.loc[changed, "employee_count"].fillna(1) + 1
    new.loc[changed, "has_item_11_disclosure"] = True
    new["has_item_11_disclosure"] = new["has_item_11_disclosure"].map(lambda value: 1.0 if value is True else 0.0 if value is False else value)
    return baseline, new


def _seed_clean_room(tmp_path, baseline):
    root = tmp_path / "clean-room"
    assert not root.resolve().is_relative_to(Path(__file__).parents[1].resolve())
    root.mkdir(parents=True)
    registry = DatasetRegistry(root / "metadata.db")
    registry.init_schema()
    registry.register({"dataset_version": "baseline", "dataset_name": "baseline",
                       "download_timestamp": "2026-07-01T00:00:00Z", "status": "success"})
    production = root / "production"
    production.mkdir(parents=True)
    connection = duckdb.connect(str(production / "analytics.duckdb"))
    connection.register("_baseline", baseline)
    connection.execute('CREATE TABLE "silver_firms_baseline" AS SELECT * FROM _baseline')
    connection.execute('CREATE TABLE "gold_scm_acquisition_v1_baseline" AS SELECT * FROM _baseline')
    connection.unregister("_baseline")
    connection.close()
    return root


def _zip_fixture(tmp_path, version="next"):
    path = tmp_path / f"{version}.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("ia_roster.csv", "Organization CRD#,Primary Business Name\n1,Fixture\n")
    return path


def test_clean_room_success_promotion_change_queue_and_registry(tmp_path):
    baseline, new = _fixture_frames(tmp_path)
    root = _seed_clean_room(tmp_path, baseline)
    result = StagedRefresh(root).run(
        dataset_version="next", previous_dataset_version="baseline",
        source_zip=_zip_fixture(tmp_path), silver_frame=new, previous_gold_frame=baseline,
    )
    assert result.status == "SUCCESS"
    assert result.promoted is True
    assert (root / "production" / "exports" / "reports" / "monthly_report.json").exists()
    assert result.change_report and result.change_report.exists()
    assert result.research_queue and result.research_queue.exists()
    connection = duckdb.connect(str(root / "production" / "analytics.duckdb"), read_only=True)
    assert connection.execute('SELECT COUNT(*) FROM "silver_firms_baseline"').fetchone()[0] == len(baseline)
    assert connection.execute('SELECT COUNT(*) FROM "silver_firms_next"').fetchone()[0] == len(new)
    assert connection.execute(f'SELECT COUNT(*) FROM "{gold_v1_table_name("next")}"').fetchone()[0] == len(new)
    connection.close()
    current = DatasetRegistry(root / "metadata.db").get_current()
    assert current["dataset_version"] == "next"
    report = __import__("json").loads(result.change_report.read_text())
    assert {event["event_type"] for event in report["events"]} >= {"NEW_FIRM", "REMOVED_FIRM", "AUM_CHANGE", "STAFFING_CHANGE", "ITEM11_CHANGE"}


@pytest.mark.parametrize("stage,expected", [
    ("download", "FAILED_DOWNLOAD"), ("zip_validation", "FAILED_VALIDATION"),
    ("silver_normalization", "FAILED_SILVER"), ("quality", "FAILED_QUALITY"),
    ("gold_v1", "FAILED_GOLD"), ("target_exports", "FAILED_EXPORT"),
    ("reporting", "FAILED_REPORTING"), ("promotion", "FAILED_PROMOTION"),
])
def test_clean_room_failures_never_promote(tmp_path, stage, expected):
    baseline, new = _fixture_frames(tmp_path)
    root = _seed_clean_room(tmp_path, baseline)
    result = StagedRefresh(root).run(
        dataset_version="next", previous_dataset_version="baseline",
        source_zip=_zip_fixture(tmp_path), silver_frame=new, previous_gold_frame=baseline,
        fail_stage=stage,
    )
    assert result.status == expected
    assert result.promoted is False
    assert DatasetRegistry(root / "metadata.db").get_current()["dataset_version"] == "baseline"
    connection = duckdb.connect(str(root / "production" / "analytics.duckdb"), read_only=True)
    assert connection.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name='silver_firms_next'").fetchone()[0] == 0
    connection.close()

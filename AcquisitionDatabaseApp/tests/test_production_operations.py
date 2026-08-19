import json
import threading
import time
from pathlib import Path

import pytest

from src import backup, production
from src.config import settings
from src.operations import OperationsRepository
from src.storage import DatasetRegistry


def _patch_paths(monkeypatch, tmp_path):
    base = tmp_path / "prod"
    for name, value in {
        "ENVIRONMENT": "PROD", "BASE_DIR": base, "DB_FILE": base / "metadata.db",
        "DUCKDB_FILE": base / "analytics.duckdb", "BACKUP_DIR": base / "backups",
        "BRONZE_DIR": base / "bronze", "GOLD_DIR": base / "gold",
        "RUN_MANIFEST_DIR": base / "run_manifests",
    }.items():
        monkeypatch.setattr(settings, name, value)
    base.mkdir(parents=True)
    (base / "bronze" / "raw").mkdir(parents=True)
    (base / "gold" / "fixture").mkdir(parents=True)


def test_run_registry_persists_stages_and_failure(tmp_path):
    repository = OperationsRepository(tmp_path / "metadata.db")
    run_id = repository.start_run(dataset_version="fixture", source_url="https://example.test", trigger_type="test")
    repository.record_stage(run_id, "download", status="FAILED_DOWNLOAD", error_message="network")
    repository.update_run(run_id, status="FAILED_DOWNLOAD", error_count=1, notes="network")
    run = repository.get_run(run_id)
    assert run["status"] == "FAILED_DOWNLOAD"
    assert repository.list_stages(run_id)[0]["stage_name"] == "download"


def test_failed_retry_cannot_demote_successful_dataset(tmp_path):
    registry = DatasetRegistry(tmp_path / "metadata.db")
    registry.init_schema()
    registry.register({"dataset_version": "fixture", "dataset_name": "fixture", "status": "success"})
    registry.register({"dataset_version": "fixture", "dataset_name": "fixture", "status": "failed", "notes": "bad zip"})
    assert registry.get_current()["status"] == "success"


def test_backup_verify_and_isolated_restore(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    OperationsRepository().init_schema()
    settings.DUCKDB_FILE.write_text("duckdb")
    (settings.BASE_DIR / "research.db").write_text("research")
    bronze = settings.BRONZE_DIR / "raw" / "fixture.zip"
    bronze.write_bytes(b"zip-fixture")
    parquet = settings.GOLD_DIR / "fixture" / "gold_scm_acquisition_v1_fixture.parquet"
    parquet.write_bytes(b"parquet-fixture")
    manifest = backup.create_backup(dataset_version="fixture")
    path = settings.BACKUP_DIR / manifest["backup_id"]
    assert backup.verify_backup(path)["valid"] is True
    restored = backup.restore_backup(path, tmp_path / "restore")
    assert restored["valid"] is True
    assert (tmp_path / "restore" / "metadata.db").stat().st_size > 0
    with pytest.raises(RuntimeError):
        backup.restore_backup(path, settings.BASE_DIR)


def test_production_refresh_no_change_is_persisted(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    import src.download
    monkeypatch.setattr(src.download, "get_latest_url", lambda: "https://sec.test/fixture.zip")
    monkeypatch.setattr(src.download, "get_discovery_status", lambda: {"discovery_source": "primary", "fallback_used": False, "discovery_error": None})
    monkeypatch.setattr(production, "get_current_dataset", lambda: {"dataset_version": "fixture", "status": "success"})
    result = production.production_refresh(pipeline_runner=lambda **_: (_ for _ in ()).throw(AssertionError("runner called")))
    assert result["status"] == "NO_CHANGE"
    runs = OperationsRepository().list_runs(1)
    assert runs[0]["status"] == "NO_CHANGE"
    assert Path(settings.RUN_MANIFEST_DIR, f"{result['run_id']}.json").exists()


def test_fallback_discovery_is_recorded_as_warning(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    import src.download
    monkeypatch.setattr(src.download, "get_latest_url", lambda: "https://sec.test/fixture.zip")
    monkeypatch.setattr(src.download, "get_discovery_status", lambda: {"discovery_source": "fallback", "fallback_used": True, "discovery_error": "SEC unavailable"})
    monkeypatch.setattr(production, "get_current_dataset", lambda: {"dataset_version": "fixture", "status": "success"})
    monkeypatch.setattr(production, "generate_monthly_report", lambda *_: None)
    result = production.production_refresh()
    assert result["status"] == "NO_CHANGE"
    repository = OperationsRepository()
    run = repository.get_run(result["run_id"])
    assert run["warning_count"] == 1
    stage = repository.list_stages(result["run_id"])[0]
    assert json.loads(stage["details_json"])["fallback_used"] is True
    with repository.connect() as connection:
        alert = connection.execute("SELECT event_type,severity FROM operational_alerts ORDER BY alert_id DESC LIMIT 1").fetchone()
    assert tuple(alert) == ("DISCOVERY_FALLBACK_USED", "WARNING")


def test_production_refresh_new_dataset_uses_staged_path(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    import src.download
    monkeypatch.setattr(src.download, "get_latest_url", lambda: "https://sec.test/new.zip")
    monkeypatch.setattr(production, "get_current_dataset", lambda: {"dataset_version": "old", "status": "success"})
    monkeypatch.setattr(production, "generate_monthly_report", lambda *_: None)
    monkeypatch.setattr(production, "compare_gold_versions", lambda *_: {"events": []})
    monkeypatch.setattr(production, "save_change_intelligence", lambda *_: None)
    monkeypatch.setattr(production, "build_research_refresh_queue", lambda *_ , **__: [])
    monkeypatch.setattr(production, "save_research_refresh_queue", lambda *_: None)
    calls = {}

    def staged(run_id, dataset_version, previous, url, operations):
        calls.update({"run_id": run_id, "dataset_version": dataset_version, "previous": previous, "url": url})
        return {"status": "success", "dataset_version": dataset_version, "rows_loaded": 1}

    monkeypatch.setattr(production, "_run_staged_dataset", staged)
    result = production.production_refresh()
    assert result["status"] == "SUCCESS"
    assert calls["dataset_version"] == "new"
    assert calls["previous"] == "old"


def test_production_refresh_returns_busy_when_another_run_holds_lock(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    started = threading.Event()
    release = threading.Event()

    def slow_run(**_):
        started.set()
        release.wait(timeout=5)
        return {"status": "NO_CHANGE"}

    monkeypatch.setattr(production, "_production_refresh_unlocked", slow_run)
    first_result = {}
    worker = threading.Thread(target=lambda: first_result.update(production.production_refresh()))
    worker.start()
    assert started.wait(timeout=5)
    assert production.production_refresh()["status"] == "BUSY"
    release.set()
    worker.join(timeout=5)
    assert first_result["status"] == "NO_CHANGE"


def test_failed_refresh_persists_run_and_alert(monkeypatch, tmp_path):
    _patch_paths(monkeypatch, tmp_path)
    import src.download
    monkeypatch.setattr(src.download, "get_latest_url", lambda: "https://sec.test/new.zip")
    monkeypatch.setattr(production, "get_current_dataset", lambda: {"dataset_version": "old", "status": "success"})
    with pytest.raises(RuntimeError):
        production.production_refresh(pipeline_runner=lambda **_: (_ for _ in ()).throw(RuntimeError("fixture failure")))
    repository = OperationsRepository()
    assert repository.list_runs(1)[0]["status"] == "FAILED_VALIDATION"
    with repository.connect() as connection:
        assert connection.execute("SELECT COUNT(*) FROM operational_alerts").fetchone()[0] >= 1

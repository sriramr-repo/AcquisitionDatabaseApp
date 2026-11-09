"""Controlled production operations built around the existing pipeline."""

from __future__ import annotations

import json
import fcntl
import shutil
import tempfile
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import duckdb
import pandas as pd

from src.alerts import AlertNotifier
from src.backup import create_backup, restore_active_bronze_from_backup
from src.change_intelligence import compare_gold_versions, save_change_intelligence
from src.config import settings
from src.gold_v1 import gold_v1_table_name
from src.metadata import get_current_dataset, list_datasets
from src.operations import OperationsRepository, utc_now
from src.research_queue import build_research_refresh_queue, save_research_refresh_queue
from src.staged_refresh import StagedRefresh, StageFailure


def _require_production() -> None:
    if not settings.is_production:
        raise RuntimeError(f"Production operation requires SCM_ENV=PROD; active environment is {settings.ENVIRONMENT}")


def _counts(dataset_version: str) -> dict[str, Any]:
    if not settings.DUCKDB_FILE.exists():
        return {"silver_rows": None, "gold_v1_rows": None, "priority_counts": {}}
    connection = duckdb.connect(str(settings.DUCKDB_FILE), read_only=True)
    try:
        result: dict[str, Any] = {}
        for name, table in {"silver_rows": f"silver_firms_{dataset_version}",
                            "gold_v1_rows": gold_v1_table_name(dataset_version)}.items():
            exists = connection.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name=?", (table,)).fetchone()[0]
            result[name] = connection.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0] if exists else None
        table = gold_v1_table_name(dataset_version)
        if result.get("gold_v1_rows") is not None:
            result["priority_counts"] = {row[0]: row[1] for row in connection.execute(f'SELECT priority_category,count(*) FROM "{table}" GROUP BY priority_category').fetchall()}
        return result
    finally:
        connection.close()


def write_run_manifest(run: dict[str, Any], *, output_dir: Path | None = None) -> Path:
    root = Path(output_dir or settings.RUN_MANIFEST_DIR)
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{run['run_id']}.json"
    path.write_text(json.dumps(run, indent=2, default=str) + "\n")
    return path


@contextmanager
def _production_refresh_lock():
    """Serialize host-local production refreshes with automatic stale recovery."""
    lock_path = settings.BASE_DIR / ".production-refresh.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle = lock_path.open("a+")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        handle.seek(0)
        handle.truncate()
        handle.write(f"pid={__import__('os').getpid()}\n")
        handle.flush()
        yield True
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def production_refresh(*, trigger_type: str = "manual", force: bool = False,
                       pipeline_runner: Callable[..., dict[str, Any]] | None = None,
                       firm_activation_manifest: Path | None = None) -> dict[str, Any]:
    with _production_refresh_lock() as acquired:
        if not acquired:
            return {"status": "BUSY", "notes": "Another production refresh is already running."}
        return _production_refresh_unlocked(trigger_type=trigger_type, force=force,
                                            pipeline_runner=pipeline_runner,
                                            firm_activation_manifest=firm_activation_manifest)


def _production_refresh_unlocked(*, trigger_type: str = "manual", force: bool = False,
                                 pipeline_runner: Callable[..., dict[str, Any]] | None = None,
                                 firm_activation_manifest: Path | None = None) -> dict[str, Any]:
    """Run the monthly flow; no-change is fully successful and side-effect free."""
    _require_production()
    from src.pipeline import run_pipeline
    runner = pipeline_runner or run_pipeline
    operations = OperationsRepository()
    notifier = AlertNotifier(operations)
    run_id = operations.start_run(dataset_version=None, source_url=None, trigger_type=trigger_type)
    started = time.perf_counter()
    backup = None
    firm_feed_selection = None
    try:
        if pipeline_runner is None:
            from src.iapd_firms import MANIFEST_URL, resolve_firm_feed_pair
            firm_feed_selection = resolve_firm_feed_pair(activation_manifest=firm_activation_manifest)
            dataset_version = firm_feed_selection.dataset_version
            url = MANIFEST_URL
            discovery = {
                "discovery_source": firm_feed_selection.discovery_mode, "fallback_used": False,
                "discovery_error": None,
                **firm_feed_selection.discovery_record(),
            }
        else:
            if firm_activation_manifest is not None:
                raise ValueError("firm activation manifests are not supported with an injected pipeline runner")
            # Preserve the injectable legacy runner used by isolated operator tests.
            from src.download import get_discovery_status, get_latest_url
            url = get_latest_url()
            discovery = get_discovery_status()
            dataset_version = Path(url).stem
        current = get_current_dataset()
        previous = current.get("dataset_version") if current else None
        operations.update_run(run_id, dataset_version=dataset_version, source_url=url, previous_dataset_version=previous)
        discovery_details = {"url": url, **discovery}
        fallback_used = bool(discovery.get("fallback_used"))
        operations.record_stage(run_id, "dataset_discovery", duration_seconds=time.perf_counter()-started,
                                warning_count=1 if fallback_used else 0,
                                details_json=json.dumps(discovery_details, default=str))
        if fallback_used:
            notifier.emit("DISCOVERY_FALLBACK_USED", str(discovery.get("discovery_error") or "SEC discovery fallback used"),
                          severity="WARNING", run_id=run_id, details=discovery_details)
            operations.update_run(run_id, warning_count=1, notes="SEC primary discovery failed; fallback URL used.")
        if current and current.get("dataset_version") == dataset_version and not force:
            operations.update_run(run_id, status="NO_CHANGE", completed_at=utc_now(), execution_duration_seconds=time.perf_counter()-started, notes="Latest canonical firm dataset is already registered successfully.")
            result = {"run_id": run_id, "status": "NO_CHANGE", "dataset_version": dataset_version,
                      "firm_feed_selection": firm_feed_selection.discovery_record() if firm_feed_selection else None}
            generate_monthly_report(dataset_version)
            write_run_manifest(result)
            return result

        backup = create_backup(dataset_version=previous, run_id=run_id)
        operations.update_run(run_id, backup_id=backup["backup_id"])
        operations.record_stage(run_id, "backup", duration_seconds=0.0, details_json=json.dumps({"backup_id": backup["backup_id"]}))
        if pipeline_runner is not None:
            result = runner(force=force)
        else:
            result = _run_staged_dataset(
                run_id, dataset_version, previous, url, operations,
                feed_pair=firm_feed_selection,
            )
        if result.get("status") not in {"success", "skipped"}:
            raise RuntimeError(result.get("notes") or "pipeline returned failure")
        actual = result.get("dataset_version", dataset_version)
        counts = _counts(actual)
        priorities = counts.get("priority_counts", {})
        operations.update_run(run_id, dataset_version=actual, status="SUCCESS", completed_at=utc_now(),
                              execution_duration_seconds=time.perf_counter()-started,
                              bronze_rows=result.get("rows_loaded"), silver_rows=counts.get("silver_rows"),
                              gold_v1_rows=counts.get("gold_v1_rows"), excluded_count=priorities.get("EXCLUDED"),
                              priority_a_count=priorities.get("PRIORITY_A"), priority_b_count=priorities.get("PRIORITY_B"),
                              priority_c_count=priorities.get("PRIORITY_C"), notes=result.get("notes"))
        run = {"run_id": run_id, "status": "SUCCESS", "dataset_version": actual, "counts": counts,
               "firm_feed_selection": firm_feed_selection.discovery_record() if firm_feed_selection else None,
               "result": result}
        if previous and previous != actual:
            report = compare_gold_versions(previous, actual)
            save_change_intelligence(report)
            queue = build_research_refresh_queue(actual, previous_version=previous, change_report=report)
            save_research_refresh_queue(queue, actual)
        generate_monthly_report(actual)
        write_run_manifest(run)
        return run
    except Exception as exc:
        if backup and backup.get("dataset_version"):
            try:
                restore_active_bronze_from_backup(backup)
            except Exception as restore_error:
                notifier.emit("RESTORE_FAILED", str(restore_error), severity="CRITICAL", run_id=run_id)
        failure_status = {
            "download": "FAILED_DOWNLOAD", "zip_validation": "FAILED_VALIDATION",
            "silver_normalization": "FAILED_SILVER", "quality": "FAILED_QUALITY",
            "gold_v1": "FAILED_GOLD", "target_exports": "FAILED_EXPORT",
            "reporting": "FAILED_REPORTING", "promotion": "FAILED_PROMOTION",
        }.get(getattr(exc, "stage", None), "FAILED_VALIDATION")
        operations.update_run(run_id, status=failure_status, completed_at=utc_now(),
                              execution_duration_seconds=time.perf_counter()-started, error_count=1, notes=str(exc))
        notifier.emit("PRODUCTION_RUN_FAILED", str(exc), run_id=run_id)
        write_run_manifest({
            "run_id": run_id,
            "status": failure_status,
            "firm_feed_selection": firm_feed_selection.discovery_record() if firm_feed_selection else None,
            "error": str(exc),
        })
        raise


def _run_staged_dataset(run_id: str, dataset_version: str, previous: str | None,
                        url: str, operations: OperationsRepository, *, feed_pair: Any) -> dict[str, Any]:
    """Download the canonical IAPD firm pair into staging before promotion."""
    import zipfile
    from src.iapd_firms import (
        download_feed, download_official_schemas, file_sha256, inspect_snapshot,
        reconcile_sec_silver, validate_artifact_hashes, validate_snapshot_counts,
    )

    if feed_pair is None or dataset_version != feed_pair.dataset_version:
        raise StageFailure("download", "resolved firm feed pair does not match the requested dataset")
    temporary_root = Path(tempfile.mkdtemp(prefix=f"scm-ria-stage-{dataset_version}-"))
    completed = False
    try:
        feeds = feed_pair.feeds()
        sec_path = temporary_root / feeds["sec"].name
        state_path = temporary_root / feeds["state"].name
        try:
            source_hashes = {
                "sec": download_feed(feeds["sec"], sec_path),
                "state": download_feed(feeds["state"], state_path),
            }
            sec_schema, state_schema = download_official_schemas(temporary_root / "schemas")
            artifact_validation = validate_artifact_hashes(
                feed_pair,
                source_hashes=source_hashes,
                schema_hashes={"sec": file_sha256(sec_schema), "state": file_sha256(state_schema)},
            )
        except Exception as exc:
            raise StageFailure("download", str(exc)) from exc
        try:
            snapshot = inspect_snapshot(
                sec_path, state_path, snapshot_date=feeds["sec"].snapshot_date,
                sec_schema=sec_schema, state_schema=state_schema,
            )
            snapshot_validation = validate_snapshot_counts(feed_pair, snapshot)
        except Exception as exc:
            raise StageFailure("zip_validation", str(exc)) from exc
        silver_frame = snapshot.firms
        if silver_frame.empty:
            raise StageFailure("silver_normalization", "normalization produced no firms")
        snapshot.report["sec_reconciliation"] = reconcile_sec_silver(snapshot, settings.DUCKDB_FILE)
        snapshot.report["source_selection"] = feed_pair.discovery_record()
        snapshot.report["activation_validation"] = {
            "artifacts": artifact_validation,
            "snapshot": snapshot_validation,
        }
        source_zip = temporary_root / f"{dataset_version}.zip"
        with zipfile.ZipFile(source_zip, "w", compression=zipfile.ZIP_STORED) as archive:
            archive.write(sec_path, sec_path.name)
            archive.write(state_path, state_path.name)
            archive.writestr("reconciliation-report.json", json.dumps(snapshot.report, indent=2, sort_keys=True) + "\n")
        previous_gold = None
        if previous and settings.DUCKDB_FILE.exists():
            connection = duckdb.connect(str(settings.DUCKDB_FILE), read_only=True)
            try:
                previous_gold = connection.execute(f'SELECT * FROM "{gold_v1_table_name(previous)}"').df()
            finally:
                connection.close()
        result = StagedRefresh(
            temporary_root, environment="PROD", repository=operations,
            production_root=settings.BASE_DIR,
        ).run(dataset_version=dataset_version, previous_dataset_version=previous,
              source_zip=source_zip, silver_frame=silver_frame,
              additional_silver_frames={
                  "firm_registrations": snapshot.registrations,
                  "firm_offices": snapshot.offices,
              },
              source_url=url,
              previous_gold_frame=previous_gold, run_id=run_id)
        if result.status != "SUCCESS":
            raise StageFailure(result.status.removeprefix("FAILED_").lower(), result.status)
        completed = True
        return {"status": "success", "dataset_version": dataset_version,
                "rows_loaded": len(silver_frame), "notes": "canonical IAPD firm staged promotion",
                "firm_reconciliation": snapshot.report}
    except Exception as exc:
        quarantine = settings.BASE_DIR / "quarantine" / "iapd-firms" / f"{dataset_version}-{run_id}"
        quarantine.parent.mkdir(parents=True, exist_ok=True)
        if quarantine.exists():
            raise RuntimeError(f"quarantine target already exists for failed firm snapshot: {quarantine}") from exc
        (temporary_root / "quarantine-report.json").write_text(json.dumps({
            "run_id": run_id,
            "dataset_version": dataset_version,
            "failed_at": utc_now(),
            "error_type": type(exc).__name__,
            "error": str(exc),
            "source_selection": feed_pair.discovery_record(),
        }, indent=2, default=str) + "\n")
        shutil.move(str(temporary_root), quarantine)
        raise
    finally:
        if completed or temporary_root.exists():
            shutil.rmtree(temporary_root, ignore_errors=True)


def production_status() -> dict[str, Any]:
    current = get_current_dataset()
    operations = OperationsRepository()
    return {"environment": settings.ENVIRONMENT, "base_dir": str(settings.BASE_DIR),
            "current_dataset": current, "latest_runs": operations.list_runs(10)}


def production_health_check() -> dict[str, Any]:
    current = get_current_dataset()
    checks = {"environment_is_prod": settings.is_production,
              "metadata_exists": settings.DB_FILE.exists(), "analytics_exists": settings.DUCKDB_FILE.exists(),
              "current_dataset_registered": current is not None}
    if current:
        checks.update(_counts(current["dataset_version"]))
    checks["healthy"] = all(value is not None and value is not False for value in checks.values() if isinstance(value, (bool, int, type(None))))
    return checks


def generate_monthly_report(dataset_version: str | None = None) -> Path:
    """Write a machine-readable operational and acquisition report."""
    current = get_current_dataset()
    version = dataset_version or (current or {}).get("dataset_version")
    if not version:
        raise ValueError("No dataset available for monthly report")
    counts = _counts(version)
    report = {
        "report_type": "production_monthly",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "environment": settings.ENVIRONMENT,
        "dataset_version": version,
        "operational": {"current_dataset": current, "latest_runs": OperationsRepository().list_runs(10)},
        "acquisition_intelligence": {"priority_counts": counts.get("priority_counts", {}), "row_counts": counts},
        "research_refresh_queue": str(settings.EXPORTS_DIR / "research_refresh" / version / "research_refresh_queue.json"),
    }
    month = datetime.now(timezone.utc).strftime("%Y-%m")
    root = settings.EXPORTS_DIR / "reports" / "monthly" / month
    root.mkdir(parents=True, exist_ok=True)
    path = root / "monthly_production_report.json"
    path.write_text(json.dumps(report, indent=2, default=str) + "\n")
    return path

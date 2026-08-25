"""Fail-closed staging and promotion runner used by clean-room acceptance."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import time
import zipfile
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Callable

import duckdb
import pandas as pd

from src.alerts import AlertNotifier
from src.gold_v1 import GoldV1Builder, gold_v1_table_name
from src.operations import OperationsRepository, utc_now
from src.storage import DatasetRegistry
from src.target_exports import export_priority_targets


class StageFailure(RuntimeError):
    def __init__(self, stage: str, message: str):
        super().__init__(f"{stage}: {message}")
        self.stage = stage


@dataclass
class StagedRefreshResult:
    run_id: str
    status: str
    dataset_version: str
    previous_dataset_version: str | None
    stage_root: Path
    promoted: bool
    change_report: Path | None = None
    research_queue: Path | None = None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _duckdb_compatible_frame(frame: pd.DataFrame) -> pd.DataFrame:
    """Prevent pandas Decimal inference from selecting an undersized DuckDB type."""
    result = frame.copy()
    for column in result.columns:
        values = result[column]
        if values.map(lambda value: isinstance(value, Decimal)).any():
            result[column] = values.map(
                lambda value: float(value) if isinstance(value, Decimal) else value
            )
    return result


class StagedRefresh:
    """Run real Gold V1/export code against an isolated staging database."""

    def __init__(self, root: Path, *, environment: str = "TEST",
                 repository: OperationsRepository | None = None,
                 production_root: Path | None = None):
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.repository = repository or OperationsRepository(self.root / "metadata.db")
        self.notifier = AlertNotifier(self.repository)
        if self.root == Path.cwd().resolve() or Path.cwd().resolve() in self.root.parents:
            # A clean-room root may be under a temp directory, never inside
            # the application repository.
            raise ValueError("clean-room root must not be inside the application repository")
        self.environment = environment
        self.production_root = Path(production_root).expanduser().resolve() if production_root else self.root / "production"

    def run(self, *, dataset_version: str, previous_dataset_version: str | None,
            source_zip: Path, silver_frame: pd.DataFrame,
            previous_gold_frame: pd.DataFrame | None = None,
            fail_stage: str | None = None, run_id: str | None = None) -> StagedRefreshResult:
        started = time.perf_counter()
        run_id = run_id or self.repository.start_run(dataset_version=dataset_version, source_url="fixture://sec",
                                                      trigger_type="clean-room", previous_dataset_version=previous_dataset_version)
        stage = self.root / "staging" / dataset_version
        stage.mkdir(parents=True, exist_ok=True)
        promoted = False
        try:
            self._stage(run_id, "download", fail_stage, lambda: self._copy_source(source_zip, stage))
            self._stage(run_id, "zip_validation", fail_stage, lambda: self._validate_zip(stage / "bronze" / "raw" / source_zip.name))
            self._stage(run_id, "silver_normalization", fail_stage, lambda: self._validate_silver(silver_frame))
            silver_frame = _duckdb_compatible_frame(silver_frame)
            stage_db = stage / "analytics.duckdb"
            connection = duckdb.connect(str(stage_db))
            try:
                connection.register("_silver_fixture", silver_frame)
                connection.execute(f'CREATE TABLE "silver_firms_{dataset_version}" AS SELECT * FROM _silver_fixture')
                connection.unregister("_silver_fixture")
                self._stage(run_id, "quality", fail_stage, lambda: self._quality(silver_frame))
                gold_frame = None
                def build_gold():
                    nonlocal gold_frame
                    gold_frame, _, _ = GoldV1Builder().materialize(
                        silver_frame, connection=connection, dataset_version=dataset_version,
                        parquet_path=stage / "gold" / f"gold_scm_acquisition_v1_{dataset_version}.parquet",
                    )
                self._stage(run_id, "gold_v1", fail_stage, build_gold)
                self._stage(run_id, "scoring_invariants", fail_stage, lambda: self._validate_gold(gold_frame, len(silver_frame)))
                self._stage(run_id, "target_exports", fail_stage, lambda: export_priority_targets(
                    dataset_version, stage / "exports" / "targets", connection=connection,
                ))
            finally:
                connection.close()
            change_path = self._write_change_report(run_id, previous_gold_frame, gold_frame, stage, fail_stage)
            queue_path = self._write_research_queue(run_id, previous_gold_frame, gold_frame, stage, fail_stage)
            if fail_stage == "reporting":
                raise StageFailure("reporting", "controlled acceptance failure")
            self._write_report(stage, dataset_version, len(silver_frame), len(gold_frame) if gold_frame is not None else 0)
            self.repository.record_stage(run_id, "reporting", rows_processed=1)
            self._stage(run_id, "promotion", fail_stage, lambda: self._promote(stage, dataset_version, previous_dataset_version))
            promoted = True
            self.repository.update_run(run_id, status="SUCCESS", completed_at=utc_now(),
                                       execution_duration_seconds=time.perf_counter()-started,
                                       silver_rows=len(silver_frame), gold_v1_rows=len(gold_frame) if gold_frame is not None else 0,
                                       notes="Clean-room staged refresh promoted after all gates.")
            return StagedRefreshResult(run_id, "SUCCESS", dataset_version, previous_dataset_version, stage, True, change_path, queue_path)
        except StageFailure as exc:
            status = {
                "zip_validation": "FAILED_VALIDATION", "silver_normalization": "FAILED_SILVER",
                "quality": "FAILED_QUALITY", "gold_v1": "FAILED_GOLD", "scoring_invariants": "FAILED_GOLD",
                "target_exports": "FAILED_EXPORT", "change_intelligence": "FAILED_EXPORT",
                "research_refresh": "FAILED_EXPORT", "reporting": "FAILED_REPORTING",
                "promotion": "FAILED_PROMOTION",
            }.get(exc.stage, f"FAILED_{exc.stage.upper()}")
            self.repository.update_run(run_id, status=status, completed_at=utc_now(),
                                       execution_duration_seconds=time.perf_counter()-started, error_count=1, notes=str(exc))
            self.notifier.emit(f"{exc.stage.upper()}_FAILED", str(exc), run_id=run_id)
            return StagedRefreshResult(run_id, status, dataset_version, previous_dataset_version, stage, promoted)

    def _stage(self, run_id: str, name: str, fail_stage: str | None, action: Callable[[], Any]) -> Any:
        started = time.perf_counter()
        try:
            if fail_stage == name:
                raise StageFailure(name, "controlled acceptance failure")
            result = action()
            self.repository.record_stage(run_id, name, duration_seconds=time.perf_counter()-started)
            return result
        except StageFailure:
            raise
        except Exception as exc:
            self.repository.record_stage(run_id, name, status=f"FAILED_{name.upper()}", duration_seconds=time.perf_counter()-started, error_message=str(exc))
            raise StageFailure(name, str(exc)) from exc

    @staticmethod
    def _copy_source(source: Path, stage: Path) -> None:
        destination = stage / "bronze" / "raw" / source.name
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    @staticmethod
    def _validate_zip(path: Path) -> None:
        if not zipfile.is_zipfile(path):
            raise ValueError("invalid ZIP")
        with zipfile.ZipFile(path) as archive:
            if archive.testzip() is not None or not archive.namelist():
                raise ValueError("ZIP CRC/member validation failed")

    @staticmethod
    def _validate_silver(frame: pd.DataFrame) -> None:
        if frame.empty or "firm_id" not in frame or frame["firm_id"].duplicated().any():
            raise ValueError("Silver must be non-empty with unique firm_id")

    @staticmethod
    def _quality(frame: pd.DataFrame) -> None:
        if frame["firm_id"].isna().any():
            raise ValueError("quality gate: null firm_id")

    @staticmethod
    def _validate_gold(frame: pd.DataFrame | None, expected_rows: int) -> None:
        if frame is None or len(frame) != expected_rows or frame["firm_id"].duplicated().any():
            raise ValueError("Gold/Silver row or uniqueness invariant failed")
        score = pd.to_numeric(frame["acquisition_score"], errors="coerce")
        eligible = frame["eligibility_status"].astype(str).str.upper().eq("ELIGIBLE")
        if score[eligible].dropna().lt(0).any() or score[eligible].dropna().gt(100).any():
            raise ValueError("acquisition score outside 0-100")
        excluded = frame["priority_category"].astype(str).str.upper().eq("EXCLUDED")
        if score[excluded].notna().any():
            raise ValueError("excluded firms must have null aggregate score")

    def _write_change_report(self, run_id, previous, current, stage, fail_stage):
        if fail_stage == "change_intelligence":
            raise StageFailure("change_intelligence", "controlled acceptance failure")
        events = []
        if previous is not None and current is not None:
            old_ids, new_ids = set(previous.firm_id), set(current.firm_id)
            events.extend({"event_type": "NEW_FIRM", "firm_id": str(x)} for x in sorted(new_ids-old_ids))
            events.extend({"event_type": "REMOVED_FIRM", "firm_id": str(x)} for x in sorted(old_ids-new_ids))
            common = old_ids & new_ids
            for firm_id in common:
                before, after = previous[previous.firm_id == firm_id].iloc[0], current[current.firm_id == firm_id].iloc[0]
                if before.get("total_aum") != after.get("total_aum"): events.append({"event_type":"AUM_CHANGE","firm_id":str(firm_id)})
                if before.get("employee_count") != after.get("employee_count"): events.append({"event_type":"STAFFING_CHANGE","firm_id":str(firm_id)})
                if before.get("has_item_11_disclosure") != after.get("has_item_11_disclosure"): events.append({"event_type":"ITEM11_CHANGE","firm_id":str(firm_id)})
                if before.get("priority_category") != after.get("priority_category"): events.append({"event_type":"PRIORITY_CHANGE","firm_id":str(firm_id)})
        path = stage / "exports" / "change_intelligence.json"; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"run_id": run_id, "events": events}, indent=2, default=str) + "\n")
        self.repository.record_stage(run_id, "change_intelligence", rows_processed=len(events))
        return path

    def _write_research_queue(self, run_id, previous, current, stage, fail_stage):
        if fail_stage == "research_refresh":
            raise StageFailure("research_refresh", "controlled acceptance failure")
        queue = []
        if current is not None:
            for _, row in current.iterrows():
                if str(row.get("priority_category")) == "PRIORITY_A":
                    queue.append({"firm_id": str(row["firm_id"]), "action": "NEW_TARGET_RESEARCH" if previous is None or row["firm_id"] not in set(previous.firm_id) else "NO_REFRESH_REQUIRED"})
        path = stage / "exports" / "research_refresh_queue.json"; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"run_id": run_id, "queue": queue}, indent=2) + "\n")
        self.repository.record_stage(run_id, "research_refresh", rows_processed=len(queue))
        return path

    @staticmethod
    def _write_report(stage, version, silver_rows, gold_rows):
        path = stage / "exports" / "reports" / "monthly_report.json"; path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({"report_type":"clean_room_monthly","dataset_version":version,"silver_rows":silver_rows,"gold_v1_rows":gold_rows}, indent=2) + "\n")

    def _promote(self, stage: Path, version: str, previous: str | None) -> None:
        target = self.production_root
        target.mkdir(parents=True, exist_ok=True)
        source_db = stage / "analytics.duckdb"; destination_db = target / "analytics.duckdb"
        if destination_db.exists():
            connection = duckdb.connect(str(destination_db)); connection.execute(f"ATTACH '{source_db}' AS staged")
            try:
                for table in [f"silver_firms_{version}", gold_v1_table_name(version)]:
                    connection.execute(f'CREATE OR REPLACE TABLE "{table}" AS SELECT * FROM staged."{table}"')
            finally:
                connection.execute("DETACH staged"); connection.close()
        else:
            shutil.copy2(source_db, destination_db)
        shutil.copytree(stage / "gold", target / "gold", dirs_exist_ok=True)
        shutil.copytree(stage / "exports", target / "exports", dirs_exist_ok=True)
        registry_db = self.repository.db_path if self.production_root != self.root / "production" else self.root / "metadata.db"
        registry = DatasetRegistry(registry_db)
        registry.init_schema()
        registry.register({"dataset_version": version, "dataset_name": version,
                           "source_url": "fixture://sec", "download_timestamp": utc_now(),
                           "file_name": f"{version}.zip", "status": "success",
                           "notes": "staged clean-room promotion"})
        bronze_source = stage / "bronze" / "raw" / f"{version}.zip"
        bronze_target = target / "bronze" / "raw" / bronze_source.name
        bronze_target.parent.mkdir(parents=True, exist_ok=True)
        temporary = bronze_target.with_name(f".{bronze_target.name}.promotion.tmp")
        shutil.copy2(bronze_source, temporary)
        os.replace(temporary, bronze_target)

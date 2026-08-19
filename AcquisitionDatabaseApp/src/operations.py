"""Persistent operational metadata for production runs, stages, and alerts."""

from __future__ import annotations

import os
import sqlite3
import subprocess
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.config import settings


RUN_STATUSES = {
    "STARTED", "NO_CHANGE", "SUCCESS", "FAILED_DISCOVERY", "FAILED_DOWNLOAD",
    "FAILED_VALIDATION", "FAILED_BRONZE", "FAILED_SILVER", "FAILED_QUALITY",
    "FAILED_GOLD", "FAILED_EXPORT", "FAILED_REPORTING", "FAILED_BACKUP",
    "FAILED_PROMOTION",
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def code_version() -> str:
    value = os.getenv("SCM_CODE_VERSION")
    if value:
        return value
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=settings.PROJECT_ROOT, text=True,
            stderr=subprocess.DEVNULL,
        ).strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


class OperationsRepository:
    """SQLite repository deliberately separate from the datasets table."""

    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path or settings.DB_FILE)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    @contextmanager
    def connect(self):
        connection = sqlite3.connect(str(self.db_path))
        connection.row_factory = sqlite3.Row
        try:
            yield connection
            connection.commit()
        finally:
            connection.close()

    def init_schema(self) -> None:
        with self.connect() as connection:
            connection.executescript("""
                CREATE TABLE IF NOT EXISTS pipeline_runs (
                    run_id TEXT PRIMARY KEY,
                    environment TEXT NOT NULL,
                    dataset_version TEXT,
                    source_url TEXT,
                    source_checksum TEXT,
                    code_version TEXT,
                    score_version TEXT,
                    config_version TEXT,
                    schema_version TEXT,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    status TEXT NOT NULL,
                    trigger_type TEXT NOT NULL,
                    execution_duration_seconds REAL,
                    bronze_rows INTEGER,
                    silver_rows INTEGER,
                    gold_v1_rows INTEGER,
                    excluded_count INTEGER,
                    priority_a_count INTEGER,
                    priority_b_count INTEGER,
                    priority_c_count INTEGER,
                    quality_score REAL,
                    warning_count INTEGER DEFAULT 0,
                    error_count INTEGER DEFAULT 0,
                    previous_dataset_version TEXT,
                    backup_id TEXT,
                    notes TEXT
                );
                CREATE TABLE IF NOT EXISTS pipeline_stages (
                    stage_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    stage_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    duration_seconds REAL,
                    rows_processed INTEGER,
                    warning_count INTEGER DEFAULT 0,
                    error_message TEXT,
                    details_json TEXT,
                    FOREIGN KEY(run_id) REFERENCES pipeline_runs(run_id)
                );
                CREATE TABLE IF NOT EXISTS operational_alerts (
                    alert_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT,
                    event_type TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    message TEXT NOT NULL,
                    details_json TEXT,
                    created_at TEXT NOT NULL,
                    acknowledged_at TEXT
                );
                CREATE TABLE IF NOT EXISTS backups (
                    backup_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    environment TEXT NOT NULL,
                    dataset_version TEXT,
                    run_id TEXT,
                    code_version TEXT,
                    score_version TEXT,
                    backup_path TEXT NOT NULL,
                    status TEXT NOT NULL,
                    manifest_json TEXT,
                    error_message TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_pipeline_runs_started ON pipeline_runs(started_at);
                CREATE INDEX IF NOT EXISTS idx_pipeline_stages_run ON pipeline_stages(run_id);
                CREATE INDEX IF NOT EXISTS idx_alerts_run ON operational_alerts(run_id);
            """)

    def start_run(self, *, dataset_version: str | None, source_url: str | None,
                  trigger_type: str, previous_dataset_version: str | None = None,
                  score_version: str = "SCM_ACQUISITION_V1") -> str:
        run_id = uuid.uuid4().hex
        with self.connect() as c:
            c.execute("""INSERT INTO pipeline_runs
                (run_id,environment,dataset_version,source_url,code_version,score_version,
                 config_version,schema_version,started_at,status,trigger_type,previous_dataset_version)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""", (
                run_id, settings.ENVIRONMENT, dataset_version, source_url, code_version(),
                score_version, "settings-v1", "silver-gold-v1", utc_now(), "STARTED",
                trigger_type, previous_dataset_version,
            ))
        return run_id

    def update_run(self, run_id: str, **fields: Any) -> None:
        allowed = {
            "dataset_version", "source_url", "source_checksum", "completed_at", "status",
            "execution_duration_seconds", "bronze_rows", "silver_rows", "gold_v1_rows",
            "excluded_count", "priority_a_count", "priority_b_count", "priority_c_count",
            "quality_score", "warning_count", "error_count", "backup_id", "notes",
            "previous_dataset_version",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Unknown run fields: {sorted(unknown)}")
        if fields.get("status") and fields["status"] not in RUN_STATUSES:
            raise ValueError(f"Unknown run status: {fields['status']}")
        if not fields:
            return
        assignments = ",".join(f"{key}=?" for key in fields)
        with self.connect() as c:
            c.execute(f"UPDATE pipeline_runs SET {assignments} WHERE run_id=?", [*fields.values(), run_id])

    def record_stage(self, run_id: str, stage_name: str, *, status: str = "SUCCESS",
                     started_at: str | None = None, completed_at: str | None = None,
                     duration_seconds: float | None = None, rows_processed: int | None = None,
                     warning_count: int = 0, error_message: str | None = None,
                     details_json: str | None = None) -> int:
        with self.connect() as c:
            cur = c.execute("""INSERT INTO pipeline_stages
                (run_id,stage_name,status,started_at,completed_at,duration_seconds,rows_processed,
                 warning_count,error_message,details_json) VALUES (?,?,?,?,?,?,?,?,?,?)""", (
                run_id, stage_name, status, started_at or utc_now(), completed_at or utc_now(),
                duration_seconds, rows_processed, warning_count, error_message, details_json,
            ))
            return int(cur.lastrowid)

    def record_alert(self, event_type: str, severity: str, message: str, *, run_id: str | None = None,
                     details_json: str | None = None) -> int:
        with self.connect() as c:
            cur = c.execute("""INSERT INTO operational_alerts
                (run_id,event_type,severity,message,details_json,created_at) VALUES (?,?,?,?,?,?)""",
                (run_id, event_type, severity, message, details_json, utc_now()))
            return int(cur.lastrowid)

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self.connect() as c:
            row = c.execute("SELECT * FROM pipeline_runs WHERE run_id=?", (run_id,)).fetchone()
        return dict(row) if row else None

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        with self.connect() as c:
            rows = c.execute("SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def list_stages(self, run_id: str) -> list[dict[str, Any]]:
        with self.connect() as c:
            rows = c.execute("SELECT * FROM pipeline_stages WHERE run_id=? ORDER BY stage_id", (run_id,)).fetchall()
        return [dict(row) for row in rows]

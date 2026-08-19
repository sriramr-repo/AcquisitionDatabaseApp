"""Separate manual-enrichment storage for acquisition target research."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import duckdb

from src.config import settings
from src.gold_v1 import gold_v1_table_name
from src.source_registry import (
    CORE_SOURCE_TYPES,
    CONFIDENCE_LEVELS as SOURCE_CONFIDENCE_LEVELS,
    OBSERVATION_STATUSES,
    OBSERVATION_VALUE_TYPES,
    SOURCE_TASK_STATUSES,
    source_metadata,
    source_url,
)


RESEARCH_STATUSES = frozenset(
    {"NOT_STARTED", "IN_PROGRESS", "RESEARCH_COMPLETE", "NEEDS_REVIEW", "STALE"}
)
CONFIDENCE_LEVELS = frozenset({"LOW", "MEDIUM", "HIGH", "VERIFIED"})
ASSESSMENT_LEVELS = frozenset({"UNKNOWN", "LOW", "MEDIUM", "HIGH"})

RESEARCH_FIELDS = (
    "research_status", "research_owner", "research_started_at",
    "research_completed_at", "last_researched_at", "founder_name",
    "founder_role", "founder_estimated_age", "founder_age_confidence",
    "founder_tenure_years", "founder_profile_notes", "ownership_type",
    "ownership_summary", "closely_held_assessment", "ownership_confidence",
    "ownership_notes", "succession_readiness_assessment", "succession_signal_strength",
    "visible_internal_successor", "successor_name", "succession_notes",
    "investment_philosophy", "portfolio_management_approach", "investment_model_fit",
    "investment_model_fit_notes", "primary_custodian", "secondary_custodian",
    "custodian_confidence", "custodian_notes", "client_niche", "geographic_focus",
    "specialty_niche", "client_profile_notes", "estimated_revenue",
    "revenue_estimation_method", "estimated_ebitda", "estimated_valuation_low",
    "estimated_valuation_high", "valuation_method", "economics_confidence",
    "transition_feasibility", "strategic_fit_assessment", "strategic_fit_notes",
    "integration_risks", "potential_deal_structure_notes", "outreach_recommendation",
    "recommended_contact_method", "recommended_message_angle", "relationship_path",
    "mutual_connection_notes",
)

CONFIDENCE_FIELDS = (
    "founder_age_confidence", "ownership_confidence", "custodian_confidence",
    "economics_confidence",
)
ASSESSMENT_FIELDS = ("succession_readiness_assessment", "succession_signal_strength")
FACTUAL_FIELDS = frozenset(
    {
        "research_owner", "founder_role", "founder_profile_notes", "investment_philosophy",
        "portfolio_management_approach", "primary_custodian", "secondary_custodian",
        "custodian_notes", "client_niche", "geographic_focus", "specialty_niche",
        "client_profile_notes", "revenue_estimation_method",
    }
)
NONNEGATIVE_FIELDS = (
    "founder_estimated_age", "founder_tenure_years", "estimated_revenue",
    "estimated_ebitda", "estimated_valuation_low", "estimated_valuation_high",
)
TIMESTAMP_FIELDS = (
    "research_started_at", "research_completed_at", "last_researched_at",
)

DOSSIER_SCHEMA = {
    "executive_snapshot": ("firm", "AUM", "acquisition_score", "priority", "screening_summary", "research_status"),
    "why_scm_should_care": ("structured_screening_reasons", "strategic_fit_assessment", "succession_readiness_assessment"),
    "firm_profile": ("SEC facts", "business model", "client profile", "staffing"),
    "founder_and_ownership": ("founder information", "ownership", "leadership continuity"),
    "succession_assessment": ("evidence", "visible_internal_successor", "transition signals"),
    "economics": ("estimated revenue", "valuation range", "confidence", "methodology"),
    "investment_and_custodian_fit": ("investment philosophy", "custodian", "compatibility"),
    "risks": ("regulatory", "integration", "cultural/operational"),
    "recommended_next_action": ("research further", "ready for outreach", "monitor", "deprioritize"),
    "sources": ("complete provenance list",),
}


def _validate_timestamp(value: Any, field: str) -> None:
    if value in (None, ""):
        return
    if not isinstance(value, str):
        raise ValueError(f"{field} must be an ISO timestamp string")
    try:
        datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field} must be a valid ISO timestamp") from exc


def _ensure_column(connection: sqlite3.Connection, table: str, column: str, declaration: str) -> None:
    columns = {row[1] for row in connection.execute(f"PRAGMA table_info({table})")}
    if column not in columns:
        connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {declaration}")


def _validate_payload(payload: dict[str, Any], existing: dict[str, Any] | None = None) -> None:
    merged = dict(existing or {})
    merged.update(payload)
    status = merged.get("research_status")
    if status not in RESEARCH_STATUSES:
        raise ValueError(f"research_status must be one of {sorted(RESEARCH_STATUSES)}")
    for field in CONFIDENCE_FIELDS:
        value = merged.get(field)
        if value not in (None, "") and value not in CONFIDENCE_LEVELS:
            raise ValueError(f"{field} must be one of {sorted(CONFIDENCE_LEVELS)}")
    for field in ASSESSMENT_FIELDS:
        value = merged.get(field)
        if value not in (None, "") and value not in ASSESSMENT_LEVELS:
            raise ValueError(f"{field} must be one of {sorted(ASSESSMENT_LEVELS)}")
    for field in NONNEGATIVE_FIELDS:
        value = merged.get(field)
        if value in (None, ""):
            continue
        try:
            if float(value) < 0:
                raise ValueError
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{field} must be a non-negative number") from exc
    low = merged.get("estimated_valuation_low")
    high = merged.get("estimated_valuation_high")
    if low not in (None, "") and high not in (None, "") and float(low) > float(high):
        raise ValueError("estimated_valuation_low must be <= estimated_valuation_high")
    for field in TIMESTAMP_FIELDS:
        _validate_timestamp(merged.get(field), field)


class ResearchRepository:
    """SQLite repository isolated from the canonical dataset registry."""

    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path or (settings.BASE_DIR / "research.db"))
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.init_schema()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(str(self.db_path))
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def init_schema(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS target_research (
                    firm_id TEXT NOT NULL,
                    dataset_version TEXT NOT NULL,
                    research_status TEXT NOT NULL DEFAULT 'NOT_STARTED',
                    research_owner TEXT,
                    research_started_at TEXT,
                    research_completed_at TEXT,
                    last_researched_at TEXT,
                    founder_name TEXT,
                    founder_role TEXT,
                    founder_estimated_age REAL,
                    founder_age_confidence TEXT,
                    founder_tenure_years REAL,
                    founder_profile_notes TEXT,
                    ownership_type TEXT,
                    ownership_summary TEXT,
                    closely_held_assessment TEXT,
                    ownership_confidence TEXT,
                    ownership_notes TEXT,
                    succession_readiness_assessment TEXT,
                    succession_signal_strength TEXT,
                    visible_internal_successor INTEGER,
                    successor_name TEXT,
                    succession_notes TEXT,
                    investment_philosophy TEXT,
                    portfolio_management_approach TEXT,
                    investment_model_fit TEXT,
                    investment_model_fit_notes TEXT,
                    primary_custodian TEXT,
                    secondary_custodian TEXT,
                    custodian_confidence TEXT,
                    custodian_notes TEXT,
                    client_niche TEXT,
                    geographic_focus TEXT,
                    specialty_niche TEXT,
                    client_profile_notes TEXT,
                    estimated_revenue REAL,
                    revenue_estimation_method TEXT,
                    estimated_ebitda REAL,
                    estimated_valuation_low REAL,
                    estimated_valuation_high REAL,
                    valuation_method TEXT,
                    economics_confidence TEXT,
                    transition_feasibility TEXT,
                    strategic_fit_assessment TEXT,
                    strategic_fit_notes TEXT,
                    integration_risks TEXT,
                    potential_deal_structure_notes TEXT,
                    outreach_recommendation TEXT,
                    recommended_contact_method TEXT,
                    recommended_message_angle TEXT,
                    relationship_path TEXT,
                    mutual_connection_notes TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (firm_id, dataset_version)
                );
                CREATE TABLE IF NOT EXISTS target_research_sources (
                    source_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    firm_id TEXT NOT NULL,
                    dataset_version TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_url TEXT,
                    source_title TEXT,
                    accessed_at TEXT,
                    field_supported TEXT NOT NULL,
                    source_notes TEXT,
                    FOREIGN KEY (firm_id, dataset_version)
                        REFERENCES target_research (firm_id, dataset_version)
                        ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_research_sources_target
                    ON target_research_sources (firm_id, dataset_version);
                CREATE TABLE IF NOT EXISTS research_source_tasks (
                    task_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    firm_id TEXT NOT NULL,
                    dataset_version TEXT NOT NULL,
                    source_type TEXT NOT NULL,
                    source_authority TEXT NOT NULL,
                    source_url TEXT,
                    source_title TEXT,
                    status TEXT NOT NULL DEFAULT 'NOT_STARTED',
                    assigned_to TEXT,
                    source_notes TEXT,
                    discovered_at TEXT,
                    retrieved_at TEXT,
                    last_reviewed_at TEXT,
                    UNIQUE(firm_id, dataset_version, source_type),
                    FOREIGN KEY (firm_id, dataset_version)
                        REFERENCES target_research (firm_id, dataset_version)
                        ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_source_tasks_filter
                    ON research_source_tasks (dataset_version, source_type, status);
                CREATE TABLE IF NOT EXISTS research_observations (
                    observation_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    firm_id TEXT NOT NULL,
                    dataset_version TEXT NOT NULL,
                    source_id INTEGER NOT NULL,
                    canonical_field TEXT NOT NULL,
                    proposed_value TEXT,
                    value_type TEXT NOT NULL,
                    confidence TEXT,
                    review_status TEXT NOT NULL DEFAULT 'PROPOSED',
                    analyst_owner TEXT,
                    reviewer TEXT,
                    reviewed_at TEXT,
                    review_notes TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (source_id) REFERENCES target_research_sources(source_id)
                        ON DELETE CASCADE,
                    FOREIGN KEY (firm_id, dataset_version)
                        REFERENCES target_research (firm_id, dataset_version)
                        ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_observations_target
                    ON research_observations (firm_id, dataset_version, review_status);
                CREATE TABLE IF NOT EXISTS historical_adv_filings (
                    filing_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    firm_id TEXT NOT NULL,
                    crd_number TEXT,
                    filing_date TEXT NOT NULL,
                    form_version TEXT,
                    source_url TEXT,
                    source_path TEXT,
                    content_hash TEXT,
                    retrieval_status TEXT NOT NULL DEFAULT 'REGISTERED',
                    metadata_json TEXT,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(firm_id, filing_date, form_version, content_hash)
                );
                """
            )
            _ensure_column(connection, "target_research_sources", "source_authority", "TEXT")
            _ensure_column(connection, "target_research_sources", "published_at", "TEXT")
            _ensure_column(connection, "target_research_sources", "retrieval_status", "TEXT DEFAULT 'DISCOVERED'")
            _ensure_column(connection, "target_research_sources", "content_hash", "TEXT")
            _ensure_column(connection, "target_research_sources", "analyst_owner", "TEXT")

    def create_research_record(self, firm_id: str, dataset_version: str, **fields: Any) -> dict[str, Any]:
        unknown = set(fields) - set(RESEARCH_FIELDS)
        if unknown:
            raise ValueError(f"Unknown research fields: {sorted(unknown)}")
        payload = {field: fields.get(field) for field in RESEARCH_FIELDS}
        payload["research_status"] = fields.get("research_status", "NOT_STARTED")
        _validate_payload(payload)
        columns = ("firm_id", "dataset_version") + RESEARCH_FIELDS
        values = [firm_id, dataset_version] + [payload[field] for field in RESEARCH_FIELDS]
        placeholders = ",".join("?" for _ in columns)
        try:
            with self._connect() as connection:
                connection.execute(
                    f"INSERT INTO target_research ({','.join(columns)}) VALUES ({placeholders})",
                    values,
                )
        except sqlite3.IntegrityError as exc:
            raise ValueError("Research record already exists") from exc
        return self.get_research_record(firm_id, dataset_version)  # type: ignore[return-value]

    def get_research_record(self, firm_id: str, dataset_version: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM target_research WHERE firm_id = ? AND dataset_version = ?",
                (firm_id, dataset_version),
            ).fetchone()
        return dict(row) if row else None

    def update_research_record(self, firm_id: str, dataset_version: str, **fields: Any) -> dict[str, Any]:
        unknown = set(fields) - set(RESEARCH_FIELDS)
        if unknown:
            raise ValueError(f"Unknown research fields: {sorted(unknown)}")
        existing = self.get_research_record(firm_id, dataset_version)
        if existing is None:
            raise KeyError("Research record does not exist")
        _validate_payload(fields, existing)
        if not fields:
            return existing
        assignments = ",".join(f"{field} = ?" for field in fields)
        values = list(fields.values()) + [firm_id, dataset_version]
        with self._connect() as connection:
            connection.execute(
                f"UPDATE target_research SET {assignments}, updated_at = CURRENT_TIMESTAMP "
                "WHERE firm_id = ? AND dataset_version = ?",
                values,
            )
        return self.get_research_record(firm_id, dataset_version)  # type: ignore[return-value]

    def update_factual_fields(
        self,
        firm_id: str,
        dataset_version: str,
        *,
        source_ids: Iterable[int],
        **fields: Any,
    ) -> dict[str, Any]:
        """Persist factual fields only after linked evidence has been captured."""
        unknown = set(fields) - FACTUAL_FIELDS
        if unknown:
            raise ValueError(f"Fields require assessment/estimate handling: {sorted(unknown)}")
        ids = [int(source_id) for source_id in source_ids]
        if not ids:
            raise ValueError("At least one evidence source is required for factual fields")
        with self._connect() as connection:
            placeholders = ",".join("?" for _ in ids)
            rows = connection.execute(
                f"""SELECT source_id, field_supported FROM target_research_sources
                WHERE firm_id = ? AND dataset_version = ? AND source_id IN ({placeholders})""",
                [firm_id, dataset_version, *ids],
            ).fetchall()
        if len(rows) != len(set(ids)):
            raise ValueError("All evidence source IDs must belong to the research record")
        supported = " ".join(str(row[1]) for row in rows)
        missing_support = [field for field in fields if field not in supported]
        if missing_support:
            raise ValueError(f"Evidence does not support fields: {sorted(missing_support)}")
        return self.update_research_record(firm_id, dataset_version, **fields)

    def add_research_source(
        self,
        firm_id: str,
        dataset_version: str,
        *,
        source_type: str,
        field_supported: str,
        source_url: str | None = None,
        source_title: str | None = None,
        accessed_at: str | None = None,
        source_notes: str | None = None,
        source_authority: str | None = None,
        published_at: str | None = None,
        retrieval_status: str = "DISCOVERED",
        content_hash: str | None = None,
        analyst_owner: str | None = None,
    ) -> int:
        if not source_type or not field_supported:
            raise ValueError("source_type and field_supported are required")
        _validate_timestamp(accessed_at, "accessed_at")
        _validate_timestamp(published_at, "published_at")
        if retrieval_status not in SOURCE_TASK_STATUSES:
            raise ValueError(f"retrieval_status must be one of {sorted(SOURCE_TASK_STATUSES)}")
        with self._connect() as connection:
            try:
                cursor = connection.execute(
                    """INSERT INTO target_research_sources
                    (firm_id, dataset_version, source_type, source_url, source_title,
                     accessed_at, field_supported, source_notes, source_authority,
                     published_at, retrieval_status, content_hash, analyst_owner)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (firm_id, dataset_version, source_type, source_url, source_title,
                     accessed_at, field_supported, source_notes, source_authority,
                     published_at, retrieval_status, content_hash, analyst_owner),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("Evidence requires an existing research record") from exc
            return int(cursor.lastrowid)

    def list_research_sources(self, firm_id: str, dataset_version: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT * FROM target_research_sources
                WHERE firm_id = ? AND dataset_version = ? ORDER BY source_id""",
                (firm_id, dataset_version),
            ).fetchall()
        return [dict(row) for row in rows]

    def initialize_source_tasks(
        self,
        dataset_version: str,
        *,
        duckdb_path: Path | str | None = None,
        source_types: Iterable[str] = CORE_SOURCE_TYPES,
        priority_categories: Iterable[str] = ("PRIORITY_A", "PRIORITY_B"),
    ) -> dict[str, int]:
        source_types = tuple(source_types)
        priority_categories = tuple(dict.fromkeys(str(value) for value in priority_categories))
        if not priority_categories:
            raise ValueError("At least one priority category is required")
        for source_type in source_types:
            source_metadata(source_type)
        with duckdb.connect(str(duckdb_path or settings.DUCKDB_FILE), read_only=True) as connection:
            table = gold_v1_table_name(dataset_version)
            placeholders = ",".join("?" for _ in priority_categories)
            firms = connection.execute(
                f'''SELECT firm_id, organization_state, website_address
                    FROM "{table}"
                    WHERE priority_category IN ({placeholders})
                    ORDER BY firm_id''',
                priority_categories,
            ).fetchall()
        created_targets = 0
        created_tasks = 0
        with self._connect() as sqlite_connection:
            for firm_id, _state, website in firms:
                firm_id = str(firm_id)
                cursor = sqlite_connection.execute(
                    "INSERT OR IGNORE INTO target_research (firm_id, dataset_version) VALUES (?, ?)",
                    (firm_id, dataset_version),
                )
                created_targets += int(cursor.rowcount == 1)
                for source_type in source_types:
                    metadata = source_metadata(source_type)
                    cursor = sqlite_connection.execute(
                        """INSERT OR IGNORE INTO research_source_tasks
                        (firm_id, dataset_version, source_type, source_authority, source_url, source_title)
                        VALUES (?, ?, ?, ?, ?, ?)""",
                        (firm_id, dataset_version, source_type, metadata["source_authority"],
                         source_url(source_type, firm_id=firm_id, website=website), metadata["source_title"]),
                    )
                    created_tasks += int(cursor.rowcount == 1)
        return {
            "target_count": len(firms),
            "targets_created": created_targets,
            "tasks_created": created_tasks,
            "total_tasks": len(firms) * len(source_types),
        }

    def list_source_tasks(
        self, *, dataset_version: str | None = None, source_type: str | None = None,
        status: str | None = None, firm_id: str | None = None,
    ) -> list[dict[str, Any]]:
        clauses, values = [], []
        for field, value in (("dataset_version", dataset_version), ("source_type", source_type),
                             ("status", status), ("firm_id", firm_id)):
            if value is not None:
                clauses.append(f"{field} = ?")
                values.append(value)
        if status is not None and status not in SOURCE_TASK_STATUSES:
            raise ValueError(f"status must be one of {sorted(SOURCE_TASK_STATUSES)}")
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM research_source_tasks" + where + " ORDER BY firm_id, source_type", values
            ).fetchall()
        return [dict(row) for row in rows]

    def update_source_task(self, task_id: int, *, status: str, assigned_to: str | None = None,
                           source_notes: str | None = None, source_url_value: str | None = None) -> dict[str, Any]:
        if status not in SOURCE_TASK_STATUSES:
            raise ValueError(f"status must be one of {sorted(SOURCE_TASK_STATUSES)}")
        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        fields = ["status = ?", "assigned_to = ?", "source_notes = ?"]
        values: list[Any] = [status, assigned_to, source_notes]
        if source_url_value is not None:
            fields.append("source_url = ?")
            values.append(source_url_value)
        if status in {"DISCOVERED", "RETRIEVED", "REVIEW_REQUIRED"}:
            fields.append("discovered_at = COALESCE(discovered_at, ?)")
            values.append(now)
        if status == "RETRIEVED":
            fields.append("retrieved_at = ?")
            values.append(now)
        if status in {"ACCEPTED", "UNAVAILABLE", "FAILED", "STALE"}:
            fields.append("last_reviewed_at = ?")
            values.append(now)
        values.append(task_id)
        with self._connect() as connection:
            connection.execute(f"UPDATE research_source_tasks SET {', '.join(fields)} WHERE task_id = ?", values)
            row = connection.execute("SELECT * FROM research_source_tasks WHERE task_id = ?", (task_id,)).fetchone()
        if row is None:
            raise KeyError("Source task does not exist")
        return dict(row)

    def register_historical_filing(self, *, firm_id: str, filing_date: str, crd_number: str | None = None,
                                   form_version: str | None = None, source_url_value: str | None = None,
                                   source_path: str | None = None, content_hash: str | None = None,
                                   retrieval_status: str = "REGISTERED", metadata_json: str | None = None) -> int:
        _validate_timestamp(filing_date, "filing_date")
        with self._connect() as connection:
            cursor = connection.execute(
                """INSERT OR IGNORE INTO historical_adv_filings
                (firm_id, crd_number, filing_date, form_version, source_url, source_path,
                 content_hash, retrieval_status, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (firm_id, crd_number, filing_date, form_version, source_url_value, source_path,
                 content_hash, retrieval_status, metadata_json),
            )
            row = connection.execute(
                """SELECT filing_id FROM historical_adv_filings
                WHERE firm_id = ? AND filing_date = ? AND form_version IS ? AND content_hash IS ?""",
                (firm_id, filing_date, form_version, content_hash),
            ).fetchone()
        return int(row[0])

    def add_observation(self, *, firm_id: str, dataset_version: str, source_id: int,
                        canonical_field: str, proposed_value: Any = None, value_type: str = "FACT",
                        confidence: str | None = None, review_status: str = "PROPOSED",
                        analyst_owner: str | None = None) -> int:
        if value_type not in OBSERVATION_VALUE_TYPES:
            raise ValueError(f"value_type must be one of {sorted(OBSERVATION_VALUE_TYPES)}")
        if confidence not in (None, "") and confidence not in SOURCE_CONFIDENCE_LEVELS:
            raise ValueError(f"confidence must be one of {sorted(SOURCE_CONFIDENCE_LEVELS)}")
        if review_status not in OBSERVATION_STATUSES:
            raise ValueError(f"review_status must be one of {sorted(OBSERVATION_STATUSES)}")
        if not canonical_field:
            raise ValueError("canonical_field is required")
        with self._connect() as connection:
            source = connection.execute(
                "SELECT firm_id, dataset_version FROM target_research_sources WHERE source_id = ?",
                (source_id,),
            ).fetchone()
            if source is None or tuple(source) != (firm_id, dataset_version):
                raise ValueError("source_id must belong to the research record")
            cursor = connection.execute(
                """INSERT INTO research_observations
                (firm_id, dataset_version, source_id, canonical_field, proposed_value,
                 value_type, confidence, review_status, analyst_owner)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (firm_id, dataset_version, source_id, canonical_field,
                 None if proposed_value is None else str(proposed_value), value_type,
                 confidence, review_status, analyst_owner),
            )
            return int(cursor.lastrowid)

    def list_observations(self, firm_id: str, dataset_version: str,
                          review_status: str | None = None) -> list[dict[str, Any]]:
        if review_status is not None and review_status not in OBSERVATION_STATUSES:
            raise ValueError(f"review_status must be one of {sorted(OBSERVATION_STATUSES)}")
        query = "SELECT * FROM research_observations WHERE firm_id = ? AND dataset_version = ?"
        values: list[Any] = [firm_id, dataset_version]
        if review_status is not None:
            query += " AND review_status = ?"
            values.append(review_status)
        query += " ORDER BY observation_id"
        with self._connect() as connection:
            rows = connection.execute(query, values).fetchall()
        return [dict(row) for row in rows]

    def review_observation(self, observation_id: int, *, review_status: str, reviewer: str,
                           review_notes: str | None = None) -> dict[str, Any]:
        if review_status not in OBSERVATION_STATUSES:
            raise ValueError(f"review_status must be one of {sorted(OBSERVATION_STATUSES)}")
        if not reviewer:
            raise ValueError("reviewer is required when reviewing an observation")
        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        with self._connect() as connection:
            connection.execute(
                """UPDATE research_observations SET review_status = ?, reviewer = ?,
                reviewed_at = ?, review_notes = ?, updated_at = CURRENT_TIMESTAMP
                WHERE observation_id = ?""",
                (review_status, reviewer, now, review_notes, observation_id),
            )
            row = connection.execute(
                "SELECT * FROM research_observations WHERE observation_id = ?", (observation_id,)
            ).fetchone()
        if row is None:
            raise KeyError("Observation does not exist")
        return dict(row)

    def source_coverage(self, dataset_version: str) -> dict[str, Any]:
        with self._connect() as connection:
            total = connection.execute(
                "SELECT COUNT(DISTINCT firm_id) FROM research_source_tasks WHERE dataset_version = ?", (dataset_version,)
            ).fetchone()[0]
            rows = connection.execute(
                """SELECT source_type, status, COUNT(*) AS count
                FROM research_source_tasks WHERE dataset_version = ?
                GROUP BY source_type, status ORDER BY source_type, status""", (dataset_version,)
            ).fetchall()
        return {"target_count": int(total), "by_source_and_status": [dict(row) for row in rows]}

    def initialize_priority_a(
        self,
        dataset_version: str,
        *,
        duckdb_path: Path | str | None = None,
        connection: duckdb.DuckDBPyConnection | None = None,
    ) -> dict[str, int]:
        owns_connection = connection is None
        connection = connection or duckdb.connect(str(duckdb_path or settings.DUCKDB_FILE), read_only=True)
        try:
            table = gold_v1_table_name(dataset_version)
            firms = connection.execute(
                f'''SELECT firm_id FROM "{table}" WHERE priority_category = 'PRIORITY_A' ORDER BY firm_id'''
            ).fetchall()
        finally:
            if owns_connection:
                connection.close()

        created = 0
        existing = 0
        with self._connect() as sqlite_connection:
            for (firm_id,) in firms:
                cursor = sqlite_connection.execute(
                    "INSERT OR IGNORE INTO target_research (firm_id, dataset_version) VALUES (?, ?)",
                    (str(firm_id), dataset_version),
                )
                if cursor.rowcount == 1:
                    created += 1
                else:
                    existing += 1
        return {"created": created, "existing": existing, "total": len(firms)}

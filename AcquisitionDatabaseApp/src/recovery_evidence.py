"""Fail-closed recovery evidence for production activation.

This module never creates provider snapshots or chooses a restore target. The
operator supplies an existing provider snapshot reference and a separately
approved, empty PostgreSQL database for destructive restore verification.
Credentials are accepted through environment-backed URLs and are never stored
in evidence manifests or subprocess arguments.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import parse_qs, unquote, urlsplit

from src.backup import create_backup, restore_backup, verify_backup
from src.config import settings
from src.metadata import get_current_dataset
from src.refresh_preflight import (
    database_fingerprint,
    database_identity,
    validate_approved_fingerprint,
)


EVIDENCE_SCHEMA_VERSION = 1
CRITICAL_TABLES = (
    "dataset_versions",
    "firms",
    "firm_facts",
    "firm_scores",
    "research_sources",
    "research_observations",
    "outreach_targets",
    "outreach_activities",
    "iapd_individual_snapshots",
    "iapd_firm_coverage",
    "users",
)
_SAFE_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")


class RecoveryEvidenceError(RuntimeError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temporary.write_text(json.dumps(dict(payload), indent=2, sort_keys=True, default=str) + "\n")
    os.replace(temporary, path)


def _required_reference(value: str, label: str) -> str:
    normalized = value.strip()
    if not _SAFE_REFERENCE.fullmatch(normalized):
        raise RecoveryEvidenceError(f"{label} is missing or contains unsupported characters")
    return normalized


def _required_timestamp(value: str, label: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise RecoveryEvidenceError(f"{label} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None:
        raise RecoveryEvidenceError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def postgres_subprocess_environment(url: str) -> dict[str, str]:
    """Translate a PostgreSQL URL into libpq variables without exposing it in argv."""
    parsed = urlsplit(url)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname or not parsed.path.strip("/"):
        raise RecoveryEvidenceError("an explicit PostgreSQL URL is required")
    if not parsed.username:
        raise RecoveryEvidenceError("PostgreSQL URL requires an explicit user")
    inherited = {
        key: os.environ[key]
        for key in ("PATH", "LANG", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR")
        if os.environ.get(key)
    }
    query = parse_qs(parsed.query)
    inherited.update({
        "PGHOST": parsed.hostname,
        "PGPORT": str(parsed.port or 5432),
        "PGDATABASE": unquote(parsed.path.lstrip("/")),
        "PGUSER": unquote(parsed.username),
        "PGPASSWORD": unquote(parsed.password or ""),
        "PGCONNECT_TIMEOUT": "15",
        "PGAPPNAME": "scm-recovery-evidence",
    })
    if query.get("sslmode"):
        inherited["PGSSLMODE"] = query["sslmode"][-1]
    if query.get("channel_binding"):
        inherited["PGCHANNELBINDING"] = query["channel_binding"][-1]
    return inherited


def _tool_path(name: str) -> str:
    configured_bin_dir = os.environ.get("SCM_POSTGRES_BIN_DIR", "").strip()
    if configured_bin_dir:
        bin_dir = Path(configured_bin_dir).expanduser()
        if not bin_dir.is_absolute():
            raise RecoveryEvidenceError("SCM_POSTGRES_BIN_DIR must be an absolute path")
        candidate = bin_dir / name
        if not candidate.is_file() or not os.access(candidate, os.X_OK):
            raise RecoveryEvidenceError(
                f"required PostgreSQL recovery tool is unavailable in SCM_POSTGRES_BIN_DIR: {name}"
            )
        return str(candidate.resolve())
    path = shutil.which(name)
    if not path:
        raise RecoveryEvidenceError(
            f"required PostgreSQL recovery tool is unavailable: {name}; "
            "set SCM_POSTGRES_BIN_DIR to the absolute PostgreSQL client bin directory"
        )
    return path


def _run_tool(arguments: list[str], *, environment: Mapping[str, str] | None = None,
              runner: Callable[..., subprocess.CompletedProcess] | None = None) -> subprocess.CompletedProcess:
    execute = runner or subprocess.run
    result = execute(
        arguments,
        env=dict(environment) if environment is not None else None,
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise RecoveryEvidenceError(f"PostgreSQL recovery tool failed: {Path(arguments[0]).name}")
    return result


def create_postgres_dump(source_url: str, dump_path: Path, *,
                         runner: Callable[..., subprocess.CompletedProcess] | None = None) -> dict[str, Any]:
    pg_dump = _tool_path("pg_dump")
    pg_restore = _tool_path("pg_restore")
    destination = Path(dump_path).expanduser().resolve()
    if destination.exists():
        raise RecoveryEvidenceError(f"refusing to overwrite PostgreSQL dump: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    environment = postgres_subprocess_environment(source_url)
    try:
        _run_tool([
            pg_dump,
            "--format=custom",
            "--no-owner",
            "--no-privileges",
            "--file",
            str(temporary),
        ], environment=environment, runner=runner)
        if not temporary.is_file() or temporary.stat().st_size == 0:
            raise RecoveryEvidenceError("pg_dump did not produce a non-empty custom archive")
        catalog_result = _run_tool([pg_restore, "--list", str(temporary)], runner=runner)
        catalog = catalog_result.stdout
        entries = [line for line in catalog.splitlines() if line and not line.startswith(";")]
        if not entries:
            raise RecoveryEvidenceError("pg_restore reported an empty archive catalog")
        catalog_path = destination.with_suffix(destination.suffix + ".catalog.txt")
        catalog_path.write_text(catalog)
        os.replace(temporary, destination)
        dump_version = _run_tool([pg_dump, "--version"], runner=runner).stdout.strip()
        restore_version = _run_tool([pg_restore, "--version"], runner=runner).stdout.strip()
        return {
            "path": str(destination),
            "sha256": _sha256(destination),
            "size": destination.stat().st_size,
            "catalog_path": str(catalog_path),
            "catalog_sha256": _sha256(catalog_path),
            "catalog_entries": len(entries),
            "pg_dump_version": dump_version,
            "pg_restore_version": restore_version,
        }
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def read_postgres_baseline(url: str) -> dict[str, Any]:
    import psycopg

    identity = database_identity(url)
    with psycopg.connect(url, connect_timeout=15, options="-c default_transaction_read_only=on") as connection:
        connection.execute("SET LOCAL statement_timeout = '60s'")
        database, schema = connection.execute("select current_database(),current_schema()").fetchone()
        if database != identity["database"] or schema != "public":
            raise RecoveryEvidenceError("connected database/schema does not match the expected target")
        ledger = connection.execute(
            "select hash,created_at from drizzle.__drizzle_migrations order by id"
        ).fetchall()
        active = connection.execute(
            "select dataset_version from public.dataset_versions "
            "order by published_at desc nulls last,dataset_version desc limit 1"
        ).fetchone()
        table_counts: dict[str, int | None] = {}
        for table in CRITICAL_TABLES:
            exists = connection.execute("select to_regclass(%s)", (f"public.{table}",)).fetchone()[0]
            table_counts[table] = connection.execute(f'SELECT count(*) FROM public."{table}"').fetchone()[0] if exists else None
    return {
        "database_target": {**identity, "fingerprint": database_fingerprint(identity)},
        "migration_ledger": [[str(row[0]), int(row[1])] for row in ledger],
        "active_dataset_version": str(active[0]) if active else None,
        "critical_table_counts": table_counts,
    }


def _assert_empty_restore_target(url: str) -> None:
    import psycopg

    with psycopg.connect(url, connect_timeout=15) as connection:
        count = connection.execute(
            "select count(*) from information_schema.tables "
            "where table_schema in ('public','drizzle') and table_type='BASE TABLE'"
        ).fetchone()[0]
    if count:
        raise RecoveryEvidenceError("isolated restore database is not empty")


def restore_postgres_dump(dump_path: Path, *, source_url: str, restore_url: str,
                          source_baseline: Mapping[str, Any],
                          runner: Callable[..., subprocess.CompletedProcess] | None = None) -> dict[str, Any]:
    source_identity = database_identity(source_url)
    restore_identity = database_identity(restore_url)
    if source_identity == restore_identity:
        raise RecoveryEvidenceError("restore target must be distinct from the production database")
    archive = Path(dump_path).expanduser().resolve()
    if not archive.is_file() or archive.stat().st_size == 0:
        raise RecoveryEvidenceError("PostgreSQL dump is missing or empty")
    _assert_empty_restore_target(restore_url)
    pg_restore = _tool_path("pg_restore")
    restore_environment = postgres_subprocess_environment(restore_url)
    _run_tool([
        pg_restore,
        "--exit-on-error",
        "--no-owner",
        "--no-privileges",
        "--dbname",
        restore_environment["PGDATABASE"],
        str(archive),
    ], environment=restore_environment, runner=runner)
    restored = read_postgres_baseline(restore_url)
    comparisons = {
        key: restored.get(key) == source_baseline.get(key)
        for key in ("migration_ledger", "active_dataset_version", "critical_table_counts")
    }
    if not all(comparisons.values()):
        raise RecoveryEvidenceError("isolated PostgreSQL restore does not match the source baseline")
    return {
        "status": "passed",
        "restore_target": restored["database_target"],
        "comparisons": comparisons,
        "restored_baseline": restored,
    }


def prove_local_restore(backup_path: Path) -> dict[str, Any]:
    root = Path(backup_path).expanduser().resolve()
    verification = verify_backup(root)
    if not verification.get("valid"):
        raise RecoveryEvidenceError("local backup failed manifest verification")
    temporary = Path(tempfile.mkdtemp(prefix="scm-local-restore-proof-"))
    try:
        restored = restore_backup(root, temporary / "restored")
        manifest = json.loads((root / "manifest.json").read_text())
        restored_hashes = {
            relative: _sha256(temporary / "restored" / relative)
            for relative in manifest.get("files", {})
        }
        expected_hashes = {relative: item["sha256"] for relative, item in manifest.get("files", {}).items()}
        if restored_hashes != expected_hashes:
            raise RecoveryEvidenceError("isolated local restore hashes differ from the backup manifest")
        return {
            "status": "passed",
            "backup_id": restored["backup_id"],
            "file_count": len(restored_hashes),
            "restored_hashes": restored_hashes,
        }
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def create_recovery_evidence(*, source_url: str, restore_url: str,
                             approved_source_fingerprint: str,
                             provider_snapshot_id: str,
                             provider_snapshot_created_at: str,
                             operator: str, restore_owner: str,
                             output_dir: Path | None = None) -> dict[str, Any]:
    if not settings.is_production:
        raise RecoveryEvidenceError("recovery evidence creation requires SCM_ENV=PROD")
    provider_id = _required_reference(provider_snapshot_id, "provider snapshot ID")
    provider_time = _required_timestamp(provider_snapshot_created_at, "provider snapshot creation time")
    operator_name = _required_reference(operator, "operator")
    owner_name = _required_reference(restore_owner, "restore owner")
    source_identity = database_identity(source_url)
    validate_approved_fingerprint(source_identity, approved_source_fingerprint)
    if source_identity == database_identity(restore_url):
        raise RecoveryEvidenceError("restore target must be distinct from the production database")
    _tool_path("pg_dump")
    _tool_path("pg_restore")
    source_baseline = read_postgres_baseline(source_url)
    _assert_empty_restore_target(restore_url)

    evidence_id = f"recovery-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    root = Path(output_dir or (settings.BACKUP_DIR / "recovery-evidence")) / evidence_id
    root.mkdir(parents=True, exist_ok=False)
    manifest_path = root / "evidence.json"
    started = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "evidence_id": evidence_id,
        "status": "running",
        "created_at": _now(),
        "operator": operator_name,
        "restore_owner": owner_name,
    }
    _atomic_json(manifest_path, started)
    try:
        current = get_current_dataset()
        local_backup = create_backup(dataset_version=(current or {}).get("dataset_version"))
        local_backup_path = settings.BACKUP_DIR / local_backup["backup_id"]
        local_restore = prove_local_restore(local_backup_path)
        dump = create_postgres_dump(source_url, root / "postgres.dump")
        postgres_restore = restore_postgres_dump(
            Path(dump["path"]),
            source_url=source_url,
            restore_url=restore_url,
            source_baseline=source_baseline,
        )
        manifest = {
            **started,
            "status": "passed",
            "completed_at": _now(),
            "source_database": source_baseline,
            "provider_snapshot": {
                "snapshot_id": provider_id,
                "created_at": provider_time,
                "operator_attested": True,
            },
            "postgres_dump": dump,
            "postgres_restore": postgres_restore,
            "local_backup": {
                "path": str(local_backup_path),
                "manifest_sha256": _sha256(local_backup_path / "manifest.json"),
                "verification": verify_backup(local_backup_path),
                "restore_proof": local_restore,
            },
        }
        _atomic_json(manifest_path, manifest)
        return {**manifest, "manifest_path": str(manifest_path)}
    except Exception as exc:
        _atomic_json(manifest_path, {
            **started,
            "status": "failed",
            "completed_at": _now(),
            "error_type": type(exc).__name__,
        })
        raise


def verify_recovery_evidence(path: Path) -> dict[str, Any]:
    manifest_path = Path(path).expanduser().resolve()
    if not manifest_path.is_file() or manifest_path.stat().st_size > 4 * 1024 * 1024:
        raise RecoveryEvidenceError("recovery evidence manifest is missing or exceeds the size limit")
    payload = json.loads(manifest_path.read_text())
    failures: list[str] = []
    if payload.get("schema_version") != EVIDENCE_SCHEMA_VERSION or payload.get("status") != "passed":
        failures.append("status")
    if not payload.get("operator") or not payload.get("restore_owner"):
        failures.append("owners")
    snapshot = payload.get("provider_snapshot") or {}
    if not snapshot.get("snapshot_id") or not snapshot.get("created_at") or snapshot.get("operator_attested") is not True:
        failures.append("provider_snapshot")
    dump = payload.get("postgres_dump") or {}
    if not isinstance(dump.get("catalog_entries"), int) or dump.get("catalog_entries", 0) <= 0:
        failures.append("postgres_catalog_entries")
    for label, path_key, hash_key in (
        ("postgres_dump", "path", "sha256"),
        ("postgres_catalog", "catalog_path", "catalog_sha256"),
    ):
        artifact = Path(str(dump.get(path_key) or ""))
        if not artifact.is_file() or _sha256(artifact) != dump.get(hash_key):
            failures.append(label)
    local = payload.get("local_backup") or {}
    local_path = Path(str(local.get("path") or ""))
    if not local_path.is_dir() or not (local_path / "manifest.json").is_file():
        failures.append("local_backup")
    else:
        if _sha256(local_path / "manifest.json") != local.get("manifest_sha256"):
            failures.append("local_manifest")
        elif not verify_backup(local_path).get("valid"):
            failures.append("local_backup_hashes")
    postgres_restore = payload.get("postgres_restore") or {}
    source_baseline = payload.get("source_database") or {}
    restored_baseline = postgres_restore.get("restored_baseline") or {}
    recalculated_comparisons = {
        key: restored_baseline.get(key) == source_baseline.get(key)
        for key in ("migration_ledger", "active_dataset_version", "critical_table_counts")
    }
    source_fingerprint = (source_baseline.get("database_target") or {}).get("fingerprint")
    restore_fingerprint = (postgres_restore.get("restore_target") or {}).get("fingerprint")
    if (
        postgres_restore.get("status") != "passed"
        or not all(recalculated_comparisons.values())
        or postgres_restore.get("comparisons") != recalculated_comparisons
        or not source_fingerprint
        or not restore_fingerprint
        or source_fingerprint == restore_fingerprint
    ):
        failures.append("postgres_restore")
    local_restore = local.get("restore_proof") or {}
    expected_local_hashes = {}
    if local_path.is_dir() and (local_path / "manifest.json").is_file():
        local_manifest = json.loads((local_path / "manifest.json").read_text())
        expected_local_hashes = {
            relative: item.get("sha256")
            for relative, item in (local_manifest.get("files") or {}).items()
        }
    if (
        local_restore.get("status") != "passed"
        or local_restore.get("restored_hashes") != expected_local_hashes
        or local_restore.get("file_count") != len(expected_local_hashes)
    ):
        failures.append("local_restore")
    return {
        "evidence_id": payload.get("evidence_id"),
        "valid": not failures,
        "failures": failures,
        "manifest_path": str(manifest_path),
    }

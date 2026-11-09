import json
import subprocess
from pathlib import Path

import pytest

from src import recovery_evidence
from src.config import settings
from src.operations import OperationsRepository
from src.refresh_preflight import database_fingerprint, database_identity


@pytest.fixture(autouse=True)
def _clear_postgres_bin_override(monkeypatch):
    monkeypatch.delenv("SCM_POSTGRES_BIN_DIR", raising=False)


def _patch_production_paths(monkeypatch, tmp_path):
    base = tmp_path / "prod"
    for name, value in {
        "ENVIRONMENT": "PROD",
        "BASE_DIR": base,
        "DB_FILE": base / "metadata.db",
        "DUCKDB_FILE": base / "analytics.duckdb",
        "BACKUP_DIR": base / "backups",
        "BRONZE_DIR": base / "bronze",
        "GOLD_DIR": base / "gold",
    }.items():
        monkeypatch.setattr(settings, name, value)
    (base / "bronze/raw").mkdir(parents=True)
    (base / "gold/fixture").mkdir(parents=True)
    OperationsRepository().init_schema()
    settings.DUCKDB_FILE.write_bytes(b"duckdb")
    (base / "research.db").write_bytes(b"research")
    (base / "bronze/raw/fixture.zip").write_bytes(b"bronze")
    (base / "gold/fixture/gold_scm_acquisition_v1_fixture.parquet").write_bytes(b"gold")


def test_postgres_dump_uses_environment_not_secret_arguments(monkeypatch, tmp_path):
    monkeypatch.setattr(recovery_evidence.shutil, "which", lambda name: f"/tools/{name}")
    calls = []

    def runner(arguments, **kwargs):
        calls.append((arguments, kwargs.get("env") or {}))
        if "--file" in arguments:
            Path(arguments[arguments.index("--file") + 1]).write_bytes(b"custom-dump")
        if "--list" in arguments:
            return subprocess.CompletedProcess(arguments, 0, stdout="1; 0 0 TABLE public firms owner\n", stderr="")
        if "--version" in arguments:
            return subprocess.CompletedProcess(arguments, 0, stdout="PostgreSQL 17.0\n", stderr="")
        return subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")

    secret = "very-secret-password"
    result = recovery_evidence.create_postgres_dump(
        f"postgres://operator:{secret}@prod.example/prod?sslmode=require",
        tmp_path / "postgres.dump",
        runner=runner,
    )
    assert result["size"] > 0
    assert result["catalog_entries"] == 1
    assert all(secret not in " ".join(arguments) for arguments, _ in calls)
    dump_call = next(item for item in calls if "--file" in item[0])
    assert dump_call[1]["PGPASSWORD"] == secret
    assert dump_call[1]["PGSSLMODE"] == "require"


def test_postgres_dump_fails_before_writing_when_tools_are_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(recovery_evidence.shutil, "which", lambda _name: None)
    destination = tmp_path / "postgres.dump"
    with pytest.raises(recovery_evidence.RecoveryEvidenceError, match="pg_dump"):
        recovery_evidence.create_postgres_dump(
            "postgres://operator:secret@prod.example/prod",
            destination,
        )
    assert not destination.exists()


def test_postgres_tool_path_uses_explicit_bin_directory(monkeypatch, tmp_path):
    bin_dir = tmp_path / "postgres-bin"
    bin_dir.mkdir()
    psql = bin_dir / "psql"
    psql.write_text("#!/bin/sh\nexit 0\n")
    psql.chmod(0o700)
    monkeypatch.setenv("SCM_POSTGRES_BIN_DIR", str(bin_dir))
    monkeypatch.setattr(recovery_evidence.shutil, "which", lambda _name: None)

    assert recovery_evidence._tool_path("psql") == str(psql.resolve())


def test_postgres_tool_path_fails_closed_for_invalid_override(monkeypatch, tmp_path):
    monkeypatch.setenv("SCM_POSTGRES_BIN_DIR", "relative/postgres-bin")
    with pytest.raises(recovery_evidence.RecoveryEvidenceError, match="absolute path"):
        recovery_evidence._tool_path("pg_dump")

    empty_bin = tmp_path / "empty-bin"
    empty_bin.mkdir()
    monkeypatch.setenv("SCM_POSTGRES_BIN_DIR", str(empty_bin))
    monkeypatch.setattr(recovery_evidence.shutil, "which", lambda name: f"/fallback/{name}")
    with pytest.raises(recovery_evidence.RecoveryEvidenceError, match="SCM_POSTGRES_BIN_DIR"):
        recovery_evidence._tool_path("pg_restore")


def test_postgres_restore_refuses_production_identity(tmp_path):
    archive = tmp_path / "postgres.dump"
    archive.write_bytes(b"dump")
    with pytest.raises(recovery_evidence.RecoveryEvidenceError, match="distinct"):
        recovery_evidence.restore_postgres_dump(
            archive,
            source_url="postgres://a:secret@ep-prod.example/prod",
            restore_url="postgres://b:other@ep-prod.example/prod",
            source_baseline={},
        )


def test_postgres_restore_selects_database_without_exposing_credentials(monkeypatch, tmp_path):
    archive = tmp_path / "postgres.dump"
    archive.write_bytes(b"dump")
    source_baseline = {
        "migration_ledger": [["hash", 1]],
        "active_dataset_version": "fixture",
        "critical_table_counts": {"firms": 10},
    }
    restored_baseline = {
        **source_baseline,
        "database_target": {
            "host": "restore.example",
            "port": 5432,
            "database": "recovery_restore",
            "fingerprint": "restore-fingerprint",
        },
    }
    calls = []
    monkeypatch.setattr(recovery_evidence, "_assert_empty_restore_target", lambda _url: None)
    monkeypatch.setattr(recovery_evidence, "_tool_path", lambda name: f"/tools/{name}")
    monkeypatch.setattr(recovery_evidence, "read_postgres_baseline", lambda _url: restored_baseline)

    def runner(arguments, **kwargs):
        calls.append((arguments, kwargs.get("env") or {}))
        return subprocess.CompletedProcess(arguments, 0, stdout="", stderr="")

    secret = "restore-secret"
    result = recovery_evidence.restore_postgres_dump(
        archive,
        source_url="postgres://operator:source-secret@prod.example/prod",
        restore_url=f"postgres://operator:{secret}@restore.example/recovery_restore",
        source_baseline=source_baseline,
        runner=runner,
    )

    restore_arguments, restore_environment = calls[0]
    assert restore_arguments[restore_arguments.index("--dbname") + 1] == "recovery_restore"
    assert secret not in " ".join(restore_arguments)
    assert restore_environment["PGPASSWORD"] == secret
    assert result["status"] == "passed"


def test_recovery_evidence_requires_timezone_and_approved_source(monkeypatch, tmp_path):
    _patch_production_paths(monkeypatch, tmp_path)
    source = "postgres://operator:secret@prod.example/prod"
    restore = "postgres://operator:secret@restore.example/restore"
    fingerprint = database_fingerprint(database_identity(source))
    with pytest.raises(recovery_evidence.RecoveryEvidenceError, match="timezone"):
        recovery_evidence.create_recovery_evidence(
            source_url=source,
            restore_url=restore,
            approved_source_fingerprint=fingerprint,
            provider_snapshot_id="snapshot-1",
            provider_snapshot_created_at="2026-11-08T12:00:00",
            operator="operator-1",
            restore_owner="owner-1",
            output_dir=tmp_path / "evidence",
        )
    with pytest.raises(ValueError, match="approved production"):
        recovery_evidence.create_recovery_evidence(
            source_url=source,
            restore_url=restore,
            approved_source_fingerprint="0" * 64,
            provider_snapshot_id="snapshot-1",
            provider_snapshot_created_at="2026-11-08T12:00:00Z",
            operator="operator-1",
            restore_owner="owner-1",
            output_dir=tmp_path / "evidence",
        )


def test_complete_recovery_evidence_and_tamper_detection(monkeypatch, tmp_path):
    _patch_production_paths(monkeypatch, tmp_path)
    source = "postgres://operator:source-password@prod.example/prod"
    restore = "postgres://operator:restore-password@restore.example/restore"
    source_target = {**database_identity(source), "fingerprint": database_fingerprint(database_identity(source))}
    restore_target = {**database_identity(restore), "fingerprint": database_fingerprint(database_identity(restore))}
    baseline = {
        "database_target": source_target,
        "migration_ledger": [["hash", 1]],
        "active_dataset_version": "fixture",
        "critical_table_counts": {"firms": 10},
    }
    monkeypatch.setattr(recovery_evidence, "get_current_dataset", lambda: {"dataset_version": "fixture"})
    monkeypatch.setattr(recovery_evidence, "read_postgres_baseline", lambda _url: baseline)
    monkeypatch.setattr(recovery_evidence, "_tool_path", lambda name: f"/tools/{name}")
    monkeypatch.setattr(recovery_evidence, "_assert_empty_restore_target", lambda _url: None)

    def fake_dump(_url, path):
        path.write_bytes(b"postgres-dump")
        catalog = path.with_suffix(path.suffix + ".catalog.txt")
        catalog.write_text("catalog\n")
        return {
            "path": str(path),
            "sha256": recovery_evidence._sha256(path),
            "size": path.stat().st_size,
            "catalog_path": str(catalog),
            "catalog_sha256": recovery_evidence._sha256(catalog),
            "catalog_entries": 1,
            "pg_dump_version": "fixture",
            "pg_restore_version": "fixture",
        }

    monkeypatch.setattr(recovery_evidence, "create_postgres_dump", fake_dump)
    monkeypatch.setattr(
        recovery_evidence,
        "restore_postgres_dump",
        lambda *_args, **_kwargs: {
            "status": "passed",
            "restore_target": restore_target,
            "comparisons": {
                "migration_ledger": True,
                "active_dataset_version": True,
                "critical_table_counts": True,
            },
            "restored_baseline": {**baseline, "database_target": restore_target},
        },
    )
    evidence = recovery_evidence.create_recovery_evidence(
        source_url=source,
        restore_url=restore,
        approved_source_fingerprint=source_target["fingerprint"],
        provider_snapshot_id="neon-branch-snapshot-1",
        provider_snapshot_created_at="2026-11-08T12:00:00Z",
        operator="operator-1",
        restore_owner="owner-1",
        output_dir=tmp_path / "evidence",
    )
    manifest_path = Path(evidence["manifest_path"])
    serialized = manifest_path.read_text()
    assert evidence["status"] == "passed"
    assert "source-password" not in serialized
    assert "restore-password" not in serialized
    assert recovery_evidence.verify_recovery_evidence(manifest_path)["valid"] is True

    Path(evidence["postgres_dump"]["path"]).write_bytes(b"tampered")
    verification = recovery_evidence.verify_recovery_evidence(manifest_path)
    assert verification["valid"] is False
    assert "postgres_dump" in verification["failures"]

"""Filesystem backup, verification, and isolated restoration utilities."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import settings
from src.operations import OperationsRepository, code_version


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _protected_paths(dataset_version: str | None) -> list[tuple[Path, str]]:
    paths = [
        (settings.DB_FILE, "metadata.db"),
        (settings.DUCKDB_FILE, "analytics.duckdb"),
        (settings.BASE_DIR / "research.db", "research.db"),
    ]
    if dataset_version:
        paths.extend([
            (settings.BRONZE_DIR / "raw" / f"{dataset_version}.zip", f"bronze/{dataset_version}.zip"),
            (settings.GOLD_DIR / dataset_version / f"gold_scm_acquisition_v1_{dataset_version}.parquet",
             f"gold/{dataset_version}/gold_scm_acquisition_v1_{dataset_version}.parquet"),
        ])
    return [(source, relative) for source, relative in paths if source.exists()]


def create_backup(*, dataset_version: str | None = None, run_id: str | None = None,
                  output_dir: Path | None = None) -> dict[str, Any]:
    repository = OperationsRepository()
    backup_id = f"backup-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    root = Path(output_dir or settings.BACKUP_DIR) / backup_id
    root.mkdir(parents=True, exist_ok=False)
    files: dict[str, Any] = {}
    try:
        for source, relative in _protected_paths(dataset_version):
            destination = root / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            files[relative] = {"sha256": _sha256(destination), "size": destination.stat().st_size}
        manifest = {
            "backup_id": backup_id, "created_at": _now(), "environment": settings.ENVIRONMENT,
            "dataset_version": dataset_version, "run_id": run_id, "code_version": code_version(),
            "score_version": "SCM_ACQUISITION_V1", "files": files,
        }
        (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        with repository.connect() as connection:
            connection.execute("""INSERT INTO backups
                (backup_id,created_at,environment,dataset_version,run_id,code_version,score_version,
                 backup_path,status,manifest_json) VALUES (?,?,?,?,?,?,?,?,?,?)""", (
                backup_id, manifest["created_at"], settings.ENVIRONMENT, dataset_version, run_id,
                manifest["code_version"], manifest["score_version"], str(root), "SUCCESS",
                json.dumps(manifest),
            ))
        return manifest
    except Exception as exc:
        with repository.connect() as connection:
            connection.execute("""INSERT OR REPLACE INTO backups
                (backup_id,created_at,environment,dataset_version,run_id,code_version,score_version,
                 backup_path,status,error_message) VALUES (?,?,?,?,?,?,?,?,?,?)""", (
                backup_id, _now(), settings.ENVIRONMENT, dataset_version, run_id, code_version(),
                "SCM_ACQUISITION_V1", str(root), "FAILED", str(exc),
            ))
        raise


def verify_backup(backup_path: Path | str) -> dict[str, Any]:
    root = Path(backup_path).expanduser().resolve()
    manifest_path = root / "manifest.json"
    if not manifest_path.is_file():
        raise ValueError(f"Backup manifest missing: {manifest_path}")
    manifest = json.loads(manifest_path.read_text())
    failures = []
    for relative, expected in manifest.get("files", {}).items():
        path = root / relative
        if not path.is_file():
            failures.append(f"missing:{relative}")
        elif _sha256(path) != expected.get("sha256"):
            failures.append(f"hash:{relative}")
    return {"backup_id": manifest.get("backup_id"), "valid": not failures, "failures": failures,
            "file_count": len(manifest.get("files", {}))}


def list_backups(limit: int = 50) -> list[dict[str, Any]]:
    repository = OperationsRepository()
    with repository.connect() as connection:
        rows = connection.execute("SELECT * FROM backups ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
    return [dict(row) for row in rows]


def restore_backup(backup_path: Path | str, target_root: Path | str) -> dict[str, Any]:
    """Restore only into an explicit isolated target, never current production paths."""
    root = Path(backup_path).expanduser().resolve()
    target = Path(target_root).expanduser().resolve()
    if target == settings.BASE_DIR.resolve() or settings.BASE_DIR.resolve() in target.parents:
        raise RuntimeError("restore_backup refuses to overwrite the active environment")
    verification = verify_backup(root)
    if not verification["valid"]:
        raise ValueError(f"Backup verification failed: {verification['failures']}")
    target.mkdir(parents=True, exist_ok=True)
    manifest = json.loads((root / "manifest.json").read_text())
    for relative in manifest.get("files", {}):
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(root / relative, destination)
    return {"target_root": str(target), "backup_id": manifest.get("backup_id"), "valid": True}


def restore_active_bronze_from_backup(manifest: dict[str, Any]) -> Path | None:
    """Recover the prior Bronze ZIP after a failed refresh, atomically."""
    dataset_version = manifest.get("dataset_version")
    if not dataset_version:
        return None
    relative = f"bronze/{dataset_version}.zip"
    source = Path(settings.BACKUP_DIR) / manifest["backup_id"] / relative
    if not source.is_file() or _sha256(source) != manifest.get("files", {}).get(relative, {}).get("sha256"):
        raise ValueError("Pre-run Bronze backup is missing or failed hash verification")
    destination = settings.BRONZE_DIR / "raw" / f"{dataset_version}.zip"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.restore.tmp")
    shutil.copy2(source, temporary)
    os.replace(temporary, destination)
    return destination

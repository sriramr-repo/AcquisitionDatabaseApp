"""Neon footprint audit, recoverable IAPD detail backup, and gated cleanup."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from src.config import settings


DETAIL_TABLES = (
    "iapd_import_issues",
    "iapd_individual_aliases",
    "iapd_individual_branch_locations",
    "iapd_individual_changes",
    "iapd_individual_current_registrations",
    "iapd_individual_current_employments",
    "iapd_individual_disclosure_flags",
    "iapd_individual_employment_history",
    "iapd_individual_other_businesses",
    "iapd_individual_previous_registrations",
    "iapd_individual_snapshot_members",
    "iapd_individuals",
)

PROTECTED_TABLES = (
    "firm_research",
    "research_sources",
    "research_evidence_captures",
    "research_observations",
    "contacts",
    "contact_sources",
    "outreach_targets",
    "outreach_activities",
    "outreach_status_history",
    "iapd_individual_live_enrichments",
    "iapd_individual_reconciliations",
    "iapd_live_captures",
)


class NeonCleanupBlocked(RuntimeError):
    """Raised when any cleanup safeguard is incomplete or inconsistent."""


def _json_bytes(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), default=str,
    ).encode("utf-8")


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(_json_bytes(value))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _existing_tables(connection: Any, names: Iterable[str]) -> set[str]:
    requested = tuple(names)
    rows = connection.execute(
        "SELECT table_name FROM information_schema.tables WHERE table_schema=current_schema() AND table_name=ANY(%s)",
        (list(requested),),
    ).fetchall()
    return {
        str(row.get("table_name") if hasattr(row, "get") else row[0])
        for row in rows
    }


def _table_counts(connection: Any, names: Iterable[str]) -> dict[str, int]:
    existing = _existing_tables(connection, names)
    counts = {}
    for name in names:
        if name not in existing:
            continue
        row = connection.execute(f'SELECT count(*) AS count FROM "{name}"').fetchone()
        counts[name] = int(row.get("count") if hasattr(row, "get") else row[0])
    return counts


def audit_neon(*, database_url: str, report_path: Path | None = None) -> dict[str, Any]:
    import psycopg

    with psycopg.connect(database_url) as connection:
        identity = connection.execute(
            "SELECT current_database(),current_schema(),current_user"
        ).fetchone()
        latest = connection.execute(
            "SELECT dataset_version FROM dataset_versions ORDER BY published_at DESC LIMIT 1"
        ).fetchone()
        sizes = connection.execute(
            """SELECT relname,pg_total_relation_size(relid),n_live_tup
                 FROM pg_stat_user_tables ORDER BY pg_total_relation_size(relid) DESC"""
        ).fetchall()
        report = {
            "status": "success",
            "audited_at": datetime.now(timezone.utc).isoformat(),
            "database": identity[0],
            "schema": identity[1],
            "user": identity[2],
            "dataset_version": str(latest[0]) if latest else None,
            "database_size_bytes": int(connection.execute(
                "SELECT pg_database_size(current_database())"
            ).fetchone()[0]),
            "tables": [
                {"table": str(name), "total_bytes": int(size), "estimated_rows": int(rows)}
                for name, size, rows in sizes
            ],
            "detail_counts": _table_counts(connection, DETAIL_TABLES),
            "protected_counts": _table_counts(connection, PROTECTED_TABLES),
        }
    if report_path:
        _write_json_atomic(report_path, report)
    return report


def backup_neon_details(
    *, database_url: str, dataset_version: str, output_root: Path | None = None,
) -> dict[str, Any]:
    import psycopg
    from psycopg.rows import dict_row

    root = Path(output_root or (settings.BASE_DIR / "iapd" / "neon-backups")).resolve()
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    temporary = Path(tempfile.mkdtemp(prefix=f".{dataset_version}.{stamp}.", dir=root))
    destination = root / f"{dataset_version}-{stamp}"
    table_reports = []
    try:
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            connection.execute("BEGIN TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            latest = connection.execute(
                "SELECT dataset_version FROM dataset_versions ORDER BY published_at DESC LIMIT 1"
            ).fetchone()
            if not latest or str(latest["dataset_version"]) != dataset_version:
                raise NeonCleanupBlocked("backup dataset does not match the active Neon dataset")
            existing = _existing_tables(connection, DETAIL_TABLES)
            for table in DETAIL_TABLES:
                if table not in existing:
                    continue
                path = temporary / f"{table}.jsonl.gz"
                digest = hashlib.sha256()
                row_count = 0
                with path.open("wb") as raw:
                    with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
                        with connection.cursor(name=f"backup_{table}") as cursor:
                            cursor.execute(f'SELECT * FROM "{table}"')
                            while rows := cursor.fetchmany(2_000):
                                for row in rows:
                                    payload = _json_bytes(dict(row)) + b"\n"
                                    zipped.write(payload)
                                    row_count += 1
                with path.open("rb") as stream:
                    for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                        digest.update(chunk)
                expected = int(connection.execute(
                    f'SELECT count(*) AS count FROM "{table}"'
                ).fetchone()["count"])
                if row_count != expected:
                    raise NeonCleanupBlocked(
                        f"backup row mismatch for {table}: expected {expected}, got {row_count}"
                    )
                table_reports.append({
                    "table": table,
                    "rows": row_count,
                    "file": path.name,
                    "compressed_bytes": path.stat().st_size,
                    "sha256": digest.hexdigest(),
                })
            connection.execute("COMMIT")
        manifest = {
            "status": "success",
            "dataset_version": dataset_version,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "tables": table_reports,
        }
        _write_json_atomic(temporary / "manifest.json", manifest)
        os.replace(temporary, destination)
        return {**manifest, "path": str(destination)}
    except Exception:
        import shutil
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def validate_cleanup_documents(
    *, dataset_version: str, bundle_manifest: dict[str, Any],
    r2_report: dict[str, Any], backup_manifest: dict[str, Any],
) -> dict[str, int]:
    if bundle_manifest.get("dataset_version") != dataset_version:
        raise NeonCleanupBlocked("bundle manifest dataset mismatch")
    if r2_report.get("status") != "success" or r2_report.get("dataset_version") != dataset_version:
        raise NeonCleanupBlocked("Cloudflare R2 publication is incomplete or mismatched")
    available = int(bundle_manifest.get("available_bundle_count") or 0)
    if int(r2_report.get("verified_bundles") or 0) != available:
        raise NeonCleanupBlocked("not every available firm bundle was verified in Cloudflare R2")
    if not r2_report.get("manifest_key") or not r2_report.get("manifest_sha256"):
        raise NeonCleanupBlocked("Cloudflare R2 activation manifest was not verified")
    if backup_manifest.get("status") != "success" or backup_manifest.get("dataset_version") != dataset_version:
        raise NeonCleanupBlocked("local Neon backup is incomplete or mismatched")
    backed_up = {entry.get("table") for entry in backup_manifest.get("tables", [])}
    missing = set(DETAIL_TABLES).difference(backed_up)
    if missing:
        raise NeonCleanupBlocked(f"Neon backup omits detail tables: {', '.join(sorted(missing))}")
    return {
        "firm_count": int(bundle_manifest.get("firm_count") or 0),
        "representative_count": int(bundle_manifest.get("representative_count") or 0),
        "available_bundle_count": available,
    }


def cleanup_neon_details(
    *, database_url: str, dataset_version: str, bundle_manifest_path: Path,
    r2_report_path: Path, backup_manifest_path: Path,
) -> dict[str, Any]:
    import psycopg

    bundle_manifest = json.loads(Path(bundle_manifest_path).read_text())
    r2_report = json.loads(Path(r2_report_path).read_text())
    backup_manifest = json.loads(Path(backup_manifest_path).read_text())
    expected = validate_cleanup_documents(
        dataset_version=dataset_version, bundle_manifest=bundle_manifest,
        r2_report=r2_report, backup_manifest=backup_manifest,
    )
    with psycopg.connect(database_url, autocommit=True) as connection:
        with connection.transaction():
            latest = connection.execute(
                "SELECT dataset_version FROM dataset_versions ORDER BY published_at DESC LIMIT 1"
            ).fetchone()
            if not latest or str(latest[0]) != dataset_version:
                raise NeonCleanupBlocked("active Neon dataset changed after backup")
            coverage = connection.execute(
                """SELECT count(*),coalesce(sum(representative_count),0)
                     FROM iapd_firm_coverage WHERE dataset_version=%s""",
                (dataset_version,),
            ).fetchone()
            if int(coverage[0]) != expected["firm_count"] or int(coverage[1]) != expected["representative_count"]:
                raise NeonCleanupBlocked("Neon coverage does not reconcile to the active R2 manifest")
            protected_before = _table_counts(connection, PROTECTED_TABLES)
            existing = _existing_tables(connection, DETAIL_TABLES)
            cleanup_tables = [table for table in DETAIL_TABLES if table in existing]
            if cleanup_tables:
                names = ",".join(f'"{table}"' for table in cleanup_tables)
                connection.execute(f"TRUNCATE TABLE {names}")
            detail_after = _table_counts(connection, cleanup_tables)
            if any(detail_after.values()):
                raise NeonCleanupBlocked("one or more Neon detail tables remain populated")
            protected_after = _table_counts(connection, PROTECTED_TABLES)
            if protected_after != protected_before:
                raise NeonCleanupBlocked("protected research or outreach counts changed during cleanup")
    return {
        "status": "success",
        "dataset_version": dataset_version,
        "cleaned_tables": cleanup_tables,
        "protected_counts": protected_after,
        "backup_manifest": str(backup_manifest_path),
        "r2_manifest_key": r2_report["manifest_key"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Neon IAPD capacity management")
    commands = parser.add_subparsers(dest="command", required=True)
    audit = commands.add_parser("audit")
    audit.add_argument("--database-url", required=True)
    audit.add_argument("--report-path", type=Path)
    backup = commands.add_parser("backup")
    backup.add_argument("--database-url", required=True)
    backup.add_argument("--dataset-version", required=True)
    backup.add_argument("--output-root", type=Path)
    cleanup = commands.add_parser("cleanup")
    cleanup.add_argument("--database-url", required=True)
    cleanup.add_argument("--dataset-version", required=True)
    cleanup.add_argument("--bundle-manifest", type=Path, required=True)
    cleanup.add_argument("--r2-report", type=Path, required=True)
    cleanup.add_argument("--backup-manifest", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "audit":
        result = audit_neon(database_url=args.database_url, report_path=args.report_path)
    elif args.command == "backup":
        result = backup_neon_details(
            database_url=args.database_url, dataset_version=args.dataset_version,
            output_root=args.output_root,
        )
    else:
        result = cleanup_neon_details(
            database_url=args.database_url, dataset_version=args.dataset_version,
            bundle_manifest_path=args.bundle_manifest, r2_report_path=args.r2_report,
            backup_manifest_path=args.backup_manifest,
        )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()

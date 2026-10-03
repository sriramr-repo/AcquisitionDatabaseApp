"""Sync versioned DuckDB gold tables into Delta Lake tables for Databricks.

Each DuckDB table ``gold_<name>_<dataset_version>`` becomes one partition of a
single Delta table ``<target>/gold_<name>``, partitioned by ``dataset_version``.
Re-running a version replaces only that partition, so the job is idempotent.

The target may be a local directory or a cloud URI (``s3://``, ``abfss://``,
``gs://``) readable by Databricks; ``storage_options`` is passed through to
``deltalake``. Registration in Unity Catalog is emitted as DDL rather than
executed, so this job never needs workspace credentials.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import duckdb

from src.config import settings


GOLD_TABLE_PATTERN = re.compile(r"^(gold_[a-z0-9_]+?)_(ia\d{8}(?:_\d+)?|[a-z0-9]+)$")
PARTITION_COLUMN = "dataset_version"


def parse_gold_table(table_name: str) -> tuple[str, str] | None:
    """Split ``gold_firms_ia07012026`` into ``("gold_firms", "ia07012026")``."""
    match = GOLD_TABLE_PATTERN.match(table_name)
    return (match.group(1), match.group(2)) if match else None


def discover_gold_tables(conn: duckdb.DuckDBPyConnection) -> list[tuple[str, str, str]]:
    rows = conn.execute(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema = 'main' AND table_name LIKE 'gold\\_%' ESCAPE '\\' "
        "ORDER BY table_name"
    ).fetchall()
    found = []
    for (table_name,) in rows:
        parsed = parse_gold_table(table_name)
        if parsed:
            found.append((table_name, *parsed))
    return found


def _is_uri(target: str) -> bool:
    return "://" in target


def unity_catalog_ddl(catalog: str, schema: str, base_name: str, location: str) -> str:
    return (
        f"CREATE TABLE IF NOT EXISTS `{catalog}`.`{schema}`.`{base_name}` "
        f"USING DELTA LOCATION '{location}';"
    )


def sync_gold_to_delta(
    *,
    target: str | Path | None = None,
    duckdb_file: Path | None = None,
    versions: list[str] | None = None,
    storage_options: dict[str, str] | None = None,
    catalog: str = "main",
    schema: str = "acquisition_gold",
    dry_run: bool = False,
) -> dict[str, Any]:
    """Write every matching gold table to its Delta table and return a manifest."""
    try:
        from deltalake import write_deltalake
    except ImportError as exc:  # pragma: no cover - exercised only without the extra
        raise RuntimeError("Install the delta extra: pip install -e '.[delta]'") from exc

    target_str = str(target or settings.EXPORTS_DIR / "delta")
    if not _is_uri(target_str):
        settings.assert_safe_path(Path(target_str))
        Path(target_str).mkdir(parents=True, exist_ok=True)

    conn = duckdb.connect(str(duckdb_file or settings.DUCKDB_FILE), read_only=True)
    try:
        tables = discover_gold_tables(conn)
        if versions:
            tables = [t for t in tables if t[2] in set(versions)]

        results = []
        for source_table, base_name, version in tables:
            location = f"{target_str.rstrip('/')}/{base_name}"
            columns = {row[0] for row in conn.execute(f'DESCRIBE "{source_table}"').fetchall()}
            projection = (
                f"* REPLACE (? AS {PARTITION_COLUMN})" if PARTITION_COLUMN in columns
                else f"*, ? AS {PARTITION_COLUMN}"
            )
            arrow = conn.execute(
                f'SELECT {projection} FROM "{source_table}"', [version]
            ).fetch_arrow_table()
            if not dry_run:
                write_deltalake(
                    location,
                    arrow,
                    mode="overwrite",
                    partition_by=[PARTITION_COLUMN],
                    predicate=f"{PARTITION_COLUMN} = '{version}'",
                    schema_mode="merge",
                    storage_options=storage_options,
                )
            results.append({
                "source_table": source_table,
                "delta_table": base_name,
                "dataset_version": version,
                "rows": arrow.num_rows,
                "location": location,
            })
    finally:
        conn.close()

    locations = sorted({(r["delta_table"], r["location"]) for r in results})
    manifest = {
        "synced_at": datetime.now(timezone.utc).isoformat(),
        "target": target_str,
        "dry_run": dry_run,
        "tables": results,
        "unity_catalog_ddl": [
            unity_catalog_ddl(catalog, schema, name, loc) for name, loc in locations
        ],
    }
    if not dry_run and not _is_uri(target_str):
        (Path(target_str) / "_sync_manifest.json").write_text(
            json.dumps(manifest, indent=2), encoding="utf-8"
        )
    return manifest

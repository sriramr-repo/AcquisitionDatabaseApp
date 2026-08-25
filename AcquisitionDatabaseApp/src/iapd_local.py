"""Local-first IAPD storage, deterministic firm bundles, and Cloudflare R2 publication."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import shutil
import tempfile
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Iterator, Protocol

import duckdb

from src.config import settings
from src.iapd import _sha256, _stable_id, _validate_zip, parse_iapd_zip


LOCAL_SCHEMA_VERSION = "iapd-local-v1"
BUNDLE_SCHEMA_VERSION = "iapd-firm-bundle-v1"
MANIFEST_SCHEMA_VERSION = "iapd-bundle-manifest-v1"
SAFE_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SAFE_OBJECT_PART = re.compile(r"^[A-Za-z0-9_-]+$")


class IAPDLocalError(RuntimeError):
    """Raised when a local build or publication invariant fails."""


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode("utf-8")


def _write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False,
    ) as handle:
        temporary = Path(handle.name)
        handle.write(_canonical_json(value))
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _replace_directory(temporary: Path, destination: Path) -> Path | None:
    """Atomically activate a directory without deleting recoverable predecessors."""
    backup = None
    if destination.exists():
        backup = destination.with_name(f"{destination.name}.previous")
        suffix = 1
        while backup.exists():
            backup = destination.with_name(f"{destination.name}.previous.{suffix}")
            suffix += 1
        os.replace(destination, backup)
    os.replace(temporary, destination)
    return backup


def _local_root(root: Path | None = None) -> Path:
    return Path(root or (settings.BASE_DIR / "iapd" / "local")).resolve()


def _bundle_root(root: Path | None = None) -> Path:
    return Path(root or (settings.BASE_DIR / "iapd" / "bundles")).resolve()


def _create_local_schema(connection: duckdb.DuckDBPyConnection) -> None:
    connection.execute(
        """CREATE TABLE iapd_snapshot (
            snapshot_id VARCHAR PRIMARY KEY,
            dataset_version VARCHAR NOT NULL,
            snapshot_date DATE NOT NULL,
            source_url VARCHAR NOT NULL,
            source_file_name VARCHAR NOT NULL,
            source_hash VARCHAR NOT NULL,
            schema_version VARCHAR NOT NULL,
            person_count BIGINT NOT NULL,
            current_link_count BIGINT NOT NULL,
            firm_count BIGINT NOT NULL,
            dashboard_link_count BIGINT NOT NULL,
            dashboard_firm_count BIGINT NOT NULL,
            duplicate_person_count BIGINT NOT NULL
        )"""
    )
    connection.execute(
        """CREATE TABLE iapd_people (
            snapshot_id VARCHAR NOT NULL,
            individual_crd VARCHAR NOT NULL,
            full_name VARCHAR,
            active_ag_registration BOOLEAN,
            composite_link VARCHAR,
            payload_json JSON NOT NULL,
            PRIMARY KEY (snapshot_id, individual_crd)
        )"""
    )
    connection.execute(
        """CREATE TABLE iapd_current_links (
            snapshot_id VARCHAR NOT NULL,
            firm_id VARCHAR NOT NULL,
            individual_crd VARCHAR NOT NULL,
            employment_id VARCHAR NOT NULL,
            employment_json JSON NOT NULL,
            PRIMARY KEY (snapshot_id, firm_id, individual_crd)
        )"""
    )


def _flush_local_rows(
    connection: duckdb.DuckDBPyConnection,
    people: list[tuple[Any, ...]],
    links: list[tuple[Any, ...]],
) -> None:
    if people:
        connection.executemany(
            "INSERT INTO iapd_people VALUES (?,?,?,?,?,?)", people,
        )
        people.clear()
    if links:
        connection.executemany(
            "INSERT INTO iapd_current_links VALUES (?,?,?,?,?)", links,
        )
        links.clear()


def build_local_store(
    *,
    source_zip: Path,
    source_url: str,
    snapshot_date: date,
    dataset_version: str,
    output_root: Path | None = None,
    expected_current_links: int | None = None,
    dashboard_firm_ids: Iterable[str] | None = None,
    batch_size: int = 2_000,
) -> dict[str, Any]:
    """Stream the official feed into an atomic, versioned local DuckDB store."""
    if batch_size < 1 or batch_size > 20_000:
        raise ValueError("batch_size must be between 1 and 20000")
    source_zip = Path(source_zip).resolve()
    _validate_zip(source_zip)
    source_hash = _sha256(source_zip)
    snapshot_id = _stable_id(snapshot_date.isoformat(), source_hash)
    root = _local_root(output_root)
    datasets_root = root / "datasets"
    datasets_root.mkdir(parents=True, exist_ok=True)
    destination = datasets_root / dataset_version
    temporary = Path(tempfile.mkdtemp(prefix=f".{dataset_version}.", dir=datasets_root))
    database_path = temporary / "iapd.duckdb"
    parquet_dir = temporary / "parquet"
    parquet_dir.mkdir()
    connection = duckdb.connect(str(database_path))
    people_rows: list[tuple[Any, ...]] = []
    link_rows: list[tuple[Any, ...]] = []
    seen_people: set[str] = set()
    duplicate_people = 0
    try:
        _create_local_schema(connection)
        connection.execute("BEGIN TRANSACTION")
        for person in parse_iapd_zip(source_zip):
            individual_crd = str(person["individual_crd"])
            if individual_crd in seen_people:
                duplicate_people += 1
                continue
            seen_people.add(individual_crd)
            people_rows.append(
                (
                    snapshot_id,
                    individual_crd,
                    person.get("full_name"),
                    person.get("active_ag_registration"),
                    person.get("composite_link"),
                    _canonical_json(person).decode("utf-8"),
                )
            )
            seen_firms: set[str] = set()
            for employment in person.get("current_employments", []):
                firm_id = employment.get("employer_firm_crd")
                if not firm_id:
                    continue
                firm_id = str(firm_id)
                if firm_id in seen_firms:
                    continue
                seen_firms.add(firm_id)
                employment_id = str(
                    employment.get("employment_id")
                    or _stable_id(individual_crd, firm_id, employment.get("employer_name"))
                )
                link_rows.append(
                    (
                        snapshot_id,
                        firm_id,
                        individual_crd,
                        employment_id,
                        _canonical_json(employment).decode("utf-8"),
                    )
                )
            if len(people_rows) >= batch_size:
                _flush_local_rows(connection, people_rows, link_rows)
        _flush_local_rows(connection, people_rows, link_rows)
        counts = connection.execute(
            """SELECT
                 (SELECT count(*) FROM iapd_people),
                 (SELECT count(*) FROM iapd_current_links),
                 (SELECT count(DISTINCT firm_id) FROM iapd_current_links)"""
        ).fetchone()
        person_count, current_link_count, firm_count = map(int, counts)
        dashboard_universe = {str(value) for value in dashboard_firm_ids} if dashboard_firm_ids is not None else None
        if dashboard_universe is None:
            dashboard_link_count = current_link_count
            dashboard_firm_count = firm_count
        else:
            connection.execute("CREATE TEMP TABLE dashboard_firms(firm_id VARCHAR PRIMARY KEY)")
            connection.executemany(
                "INSERT INTO dashboard_firms VALUES (?)",
                [(firm_id,) for firm_id in sorted(dashboard_universe)],
            )
            dashboard_link_count, dashboard_firm_count = map(int, connection.execute(
                """SELECT count(*),count(DISTINCT l.firm_id)
                     FROM iapd_current_links l JOIN dashboard_firms f USING(firm_id)"""
            ).fetchone())
        if expected_current_links is not None and dashboard_link_count != expected_current_links:
            raise IAPDLocalError(
                f"dashboard link invariant failed: expected {expected_current_links}, got {dashboard_link_count}"
            )
        connection.execute(
            "INSERT INTO iapd_snapshot VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                snapshot_id, dataset_version, snapshot_date, source_url, source_zip.name,
                source_hash, LOCAL_SCHEMA_VERSION, person_count, current_link_count,
                firm_count, dashboard_link_count, dashboard_firm_count, duplicate_people,
            ),
        )
        connection.execute("COMMIT")
        for table in ("iapd_snapshot", "iapd_people", "iapd_current_links"):
            target = (parquet_dir / f"{table}.parquet").as_posix().replace("'", "''")
            connection.execute(
                f"COPY {table} TO '{target}' (FORMAT PARQUET, COMPRESSION ZSTD)"
            )
        connection.execute("CHECKPOINT")
    except Exception:
        try:
            connection.execute("ROLLBACK")
        except Exception:
            pass
        connection.close()
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    connection.close()
    build_manifest = {
        "schema_version": LOCAL_SCHEMA_VERSION,
        "dataset_version": dataset_version,
        "snapshot_id": snapshot_id,
        "snapshot_date": snapshot_date.isoformat(),
        "source_url": source_url,
        "source_file_name": source_zip.name,
        "source_hash": source_hash,
        "person_count": person_count,
        "current_link_count": current_link_count,
        "firm_count": firm_count,
        "dashboard_link_count": dashboard_link_count,
        "dashboard_firm_count": dashboard_firm_count,
        "duplicate_person_count": duplicate_people,
        "completed": True,
    }
    _write_json_atomic(temporary / "build-manifest.json", build_manifest)
    backup = _replace_directory(temporary, destination)
    _write_json_atomic(
        root / "current.json",
        {
            "schema_version": LOCAL_SCHEMA_VERSION,
            "dataset_version": dataset_version,
            "snapshot_id": snapshot_id,
            "dataset_path": str(destination),
            "source_hash": source_hash,
        },
    )
    return {**build_manifest, "path": str(destination), "backup": str(backup) if backup else None}


def load_firm_ids(
    *, source_duckdb: Path, table_name: str, firm_id_column: str = "firm_id"
) -> set[str]:
    if not SAFE_IDENTIFIER.fullmatch(table_name) or not SAFE_IDENTIFIER.fullmatch(firm_id_column):
        raise ValueError("table and column names must be safe SQL identifiers")
    with duckdb.connect(str(source_duckdb), read_only=True) as connection:
        rows = connection.execute(
            f"SELECT DISTINCT CAST({firm_id_column} AS VARCHAR) FROM {table_name} WHERE {firm_id_column} IS NOT NULL"
        ).fetchall()
    return {str(row[0]) for row in rows}


def _bundle_representative(payload: dict[str, Any], employment: dict[str, Any]) -> dict[str, Any]:
    disclosures = payload.get("disclosures", [])
    disclosure_categories = sorted({
        category
        for disclosure in disclosures
        for category, value in disclosure.items()
        if value is True
    })
    person = {
        key: payload.get(key)
        for key in (
            "individual_crd", "first_name", "middle_name", "last_name", "suffix",
            "full_name", "active_ag_registration", "composite_link",
        )
    }
    person["current_employment"] = {
        key: employment.get(key)
        for key in (
            "employment_id", "employer_firm_crd", "employer_name", "address_line_1",
            "address_line_2", "city", "state", "postal_code", "country",
        )
    }
    person["current_registrations"] = employment.get("registrations", [])
    person["has_disclosures"] = any(
        any(value is True for value in disclosure.values())
        for disclosure in disclosures
    )
    person["disclosure_categories"] = disclosure_categories
    person["has_other_business"] = bool(payload.get("other_businesses"))
    person["other_business_count"] = len(payload.get("other_businesses", []))
    person["freshness"] = "monthly_confirmed"
    return person


def _write_firm_bundle(
    *, firms_dir: Path, dataset_version: str, snapshot: dict[str, Any],
    firm_id: str, representatives: list[dict[str, Any]],
) -> dict[str, Any]:
    payload = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "dataset_version": dataset_version,
        "snapshot_id": snapshot["snapshot_id"],
        "snapshot_date": snapshot["snapshot_date"],
        "generated_at": f"{snapshot['snapshot_date']}T00:00:00Z",
        "source": {
            "url": snapshot["source_url"],
            "file_name": snapshot["source_file_name"],
            "sha256": snapshot["source_hash"],
        },
        "firm_id": firm_id,
        "representative_count": len(representatives),
        "representatives": representatives,
    }
    relative_path = Path("firms") / f"{firm_id}.json.gz"
    path = firms_dir.parent / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("wb") as raw:
        with gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed:
            compressed.write(_canonical_json(payload))
    digest = _sha256(path)
    return {
        "firm_id": firm_id,
        "status": "AVAILABLE",
        "representative_count": len(representatives),
        "relative_path": relative_path.as_posix(),
        "object_key": f"iapd/{dataset_version}/firms/{firm_id}.json.gz",
        "sha256": digest,
        "compressed_bytes": path.stat().st_size,
    }


def generate_firm_bundles(
    *, dataset_version: str, local_root: Path | None = None,
    output_root: Path | None = None, firm_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Stream the local store into deterministic per-firm gzip JSON bundles."""
    local_dataset = _local_root(local_root) / "datasets" / dataset_version
    database_path = local_dataset / "iapd.duckdb"
    if not database_path.is_file():
        raise FileNotFoundError(f"local IAPD store not found: {database_path}")
    root = _bundle_root(output_root)
    root.mkdir(parents=True, exist_ok=True)
    destination = root / dataset_version
    temporary = Path(tempfile.mkdtemp(prefix=f".{dataset_version}.", dir=root))
    firms_dir = temporary / "firms"
    firms_dir.mkdir()
    connection = duckdb.connect(str(database_path), read_only=True)
    snapshot_row = connection.execute(
        """SELECT snapshot_id,CAST(snapshot_date AS VARCHAR),source_url,
                  source_file_name,source_hash,person_count,current_link_count,firm_count,
                  dashboard_link_count,dashboard_firm_count
             FROM iapd_snapshot LIMIT 1"""
    ).fetchone()
    if not snapshot_row:
        connection.close()
        shutil.rmtree(temporary, ignore_errors=True)
        raise IAPDLocalError("local IAPD snapshot metadata is missing")
    snapshot = dict(zip(
        ("snapshot_id", "snapshot_date", "source_url", "source_file_name", "source_hash",
         "person_count", "current_link_count", "linked_firm_count",
         "dashboard_link_count", "dashboard_firm_count"), snapshot_row,
    ))
    entries: dict[str, dict[str, Any]] = {}
    cursor = connection.execute(
        """SELECT l.firm_id,p.payload_json,l.employment_json
             FROM iapd_current_links l
             JOIN iapd_people p USING(snapshot_id,individual_crd)
            ORDER BY l.firm_id,l.individual_crd,l.employment_id"""
    )
    universe = {str(value) for value in firm_ids} if firm_ids is not None else None
    current_firm: str | None = None
    representatives: list[dict[str, Any]] = []
    try:
        while rows := cursor.fetchmany(2_000):
            for firm_id, payload_json, employment_json in rows:
                firm_id = str(firm_id)
                if universe is not None and firm_id not in universe:
                    continue
                if current_firm is not None and firm_id != current_firm:
                    entries[current_firm] = _write_firm_bundle(
                        firms_dir=firms_dir, dataset_version=dataset_version,
                        snapshot=snapshot, firm_id=current_firm,
                        representatives=representatives,
                    )
                    representatives = []
                current_firm = firm_id
                payload = json.loads(payload_json) if isinstance(payload_json, str) else payload_json
                employment = json.loads(employment_json) if isinstance(employment_json, str) else employment_json
                representatives.append(_bundle_representative(payload, employment))
        if current_firm is not None:
            entries[current_firm] = _write_firm_bundle(
                firms_dir=firms_dir, dataset_version=dataset_version,
                snapshot=snapshot, firm_id=current_firm,
                representatives=representatives,
            )
    except Exception:
        connection.close()
        shutil.rmtree(temporary, ignore_errors=True)
        raise
    connection.close()
    universe = universe if universe is not None else set(entries)
    manifest_entries = []
    for firm_id in sorted(universe):
        manifest_entries.append(entries.get(firm_id) or {
            "firm_id": firm_id,
            "status": "NO_CURRENT_REPRESENTATIVE",
            "representative_count": 0,
            "relative_path": None,
            "object_key": None,
            "sha256": None,
            "compressed_bytes": 0,
        })
    available = sum(entry["status"] == "AVAILABLE" for entry in manifest_entries)
    representative_count = sum(int(entry["representative_count"]) for entry in manifest_entries)
    expected_links = int(snapshot["dashboard_link_count"] if firm_ids is not None else snapshot["current_link_count"])
    if representative_count != expected_links:
        shutil.rmtree(temporary, ignore_errors=True)
        raise IAPDLocalError(
            f"bundle link invariant failed: expected {expected_links}, got {representative_count}"
        )
    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "bundle_schema_version": BUNDLE_SCHEMA_VERSION,
        "dataset_version": dataset_version,
        "snapshot_id": snapshot["snapshot_id"],
        "snapshot_date": snapshot["snapshot_date"],
        "generated_at": f"{snapshot['snapshot_date']}T00:00:00Z",
        "source_hash": snapshot["source_hash"],
        "firm_count": len(manifest_entries),
        "available_bundle_count": available,
        "unavailable_bundle_count": len(manifest_entries) - available,
        "representative_count": representative_count,
        "entries": manifest_entries,
    }
    _write_json_atomic(temporary / "manifest.json", manifest)
    manifest["manifest_sha256"] = _sha256(temporary / "manifest.json")
    _write_json_atomic(temporary / "manifest.sha256.json", {
        "dataset_version": dataset_version,
        "manifest_sha256": manifest["manifest_sha256"],
    })
    backup = _replace_directory(temporary, destination)
    return {
        **{key: value for key, value in manifest.items() if key != "entries"},
        "path": str(destination),
        "backup": str(backup) if backup else None,
    }


class R2ObjectClient(Protocol):
    def head_bucket(self, **kwargs: Any) -> dict[str, Any]: ...
    def head_object(self, **kwargs: Any) -> dict[str, Any]: ...
    def get_object(self, **kwargs: Any) -> dict[str, Any]: ...
    def put_object(self, **kwargs: Any) -> dict[str, Any]: ...


@dataclass(frozen=True)
class R2Config:
    account_id: str
    access_key_id: str
    secret_access_key: str
    bucket: str
    session_token: str | None = None

    @classmethod
    def from_environment(cls) -> "R2Config":
        names = {
            "account_id": "CLOUDFLARE_R2_ACCOUNT_ID",
            "access_key_id": "CLOUDFLARE_R2_ACCESS_KEY_ID",
            "secret_access_key": "CLOUDFLARE_R2_SECRET_ACCESS_KEY",
            "bucket": "CLOUDFLARE_R2_BUCKET",
        }
        values = {field: os.getenv(name) for field, name in names.items()}
        missing = [names[field] for field, value in values.items() if not value]
        if missing:
            raise IAPDLocalError(f"missing Cloudflare R2 configuration: {', '.join(missing)}")
        return cls(
            **values,  # type: ignore[arg-type]
            session_token=os.getenv("CLOUDFLARE_R2_SESSION_TOKEN") or None,
        )

    @property
    def endpoint_url(self) -> str:
        return f"https://{self.account_id}.r2.cloudflarestorage.com"


def create_r2_client(config: R2Config) -> R2ObjectClient:
    try:
        import boto3
    except ImportError as exc:
        raise IAPDLocalError("boto3 is required for Cloudflare R2 publication") from exc
    options = {
        "endpoint_url": config.endpoint_url,
        "region_name": "auto",
        "aws_access_key_id": config.access_key_id,
        "aws_secret_access_key": config.secret_access_key,
    }
    if config.session_token:
        options["aws_session_token"] = config.session_token
    return boto3.client(
        "s3", **options,
    )


def _head_matches(client: R2ObjectClient, bucket: str, key: str, digest: str, size: int) -> bool:
    try:
        response = client.head_object(Bucket=bucket, Key=key)
    except Exception as exc:
        code = getattr(exc, "response", {}).get("Error", {}).get("Code")
        if str(code) in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise
    metadata = {str(k).lower(): str(v) for k, v in (response.get("Metadata") or {}).items()}
    return metadata.get("sha256") == digest and int(response.get("ContentLength") or -1) == size


def _read_r2_object(client: R2ObjectClient, bucket: str, key: str) -> tuple[bytes, dict[str, str]] | None:
    try:
        response = client.get_object(Bucket=bucket, Key=key)
    except Exception as exc:
        code = getattr(exc, "response", {}).get("Error", {}).get("Code")
        if str(code) in {"404", "NoSuchKey", "NotFound"}:
            return None
        raise
    body = response.get("Body")
    if body is None:
        raise IAPDLocalError(f"R2 object has no body: {key}")
    payload = body.read() if hasattr(body, "read") else bytes(body)
    metadata = {str(k).lower(): str(v) for k, v in (response.get("Metadata") or {}).items()}
    return payload, metadata


def _validate_publication_manifest(manifest: dict[str, Any]) -> tuple[str, list[dict[str, Any]]]:
    dataset_version = str(manifest.get("dataset_version") or "")
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION or not SAFE_OBJECT_PART.fullmatch(dataset_version):
        raise IAPDLocalError("bundle manifest contract is invalid")
    entries = manifest.get("entries")
    if not isinstance(entries, list) or int(manifest.get("firm_count", -1)) != len(entries):
        raise IAPDLocalError("bundle manifest firm count is invalid")
    seen: set[str] = set()
    available = unavailable = representatives = 0
    for entry in entries:
        firm_id = str(entry.get("firm_id") or "")
        if not SAFE_OBJECT_PART.fullmatch(firm_id) or firm_id in seen:
            raise IAPDLocalError("bundle manifest contains an invalid or duplicate firm identifier")
        seen.add(firm_id)
        status = entry.get("status")
        if status == "AVAILABLE":
            available += 1
            expected_relative = f"firms/{firm_id}.json.gz"
            if entry.get("relative_path") != expected_relative or not re.fullmatch(r"[a-f0-9]{64}", str(entry.get("sha256") or "")):
                raise IAPDLocalError(f"bundle manifest entry is invalid: {firm_id}")
            representatives += int(entry.get("representative_count") or 0)
        elif status == "NO_CURRENT_REPRESENTATIVE":
            unavailable += 1
        else:
            raise IAPDLocalError(f"bundle manifest status is invalid: {firm_id}")
    if (
        int(manifest.get("available_bundle_count") or 0) != available
        or int(manifest.get("unavailable_bundle_count") or 0) != unavailable
        or int(manifest.get("representative_count") or 0) != representatives
    ):
        raise IAPDLocalError("bundle manifest aggregate counts are invalid")
    return dataset_version, entries


def publish_bundles_to_r2(
    *, manifest_path: Path, config: R2Config | None = None,
    client: R2ObjectClient | None = None, report_path: Path | None = None,
    force: bool = False, workers: int = 16,
) -> dict[str, Any]:
    """Publish verified bundles and atomically activate a manifest last.

    Objects are content-addressed, so a failed publication cannot invalidate
    the currently active manifest. ``force`` re-uploads every bundle while
    retaining the prior activation manifest under an immutable hash key.
    """
    config = config or R2Config.from_environment()
    if workers < 1 or workers > 64:
        raise ValueError("R2 upload workers must be between 1 and 64")
    client = client or create_r2_client(config)
    client.head_bucket(Bucket=config.bucket)
    manifest_path = Path(manifest_path).resolve()
    manifest = json.loads(manifest_path.read_text())
    root = manifest_path.parent
    dataset_version, entries = _validate_publication_manifest(manifest)
    published_manifest = json.loads(json.dumps(manifest))
    published_entries = {str(entry["firm_id"]): entry for entry in published_manifest["entries"]}
    manifest_key = f"iapd/{dataset_version}/manifest.json"
    upload_jobs: list[tuple[str, Path, str, str, int]] = []
    for entry in entries:
        if entry["status"] != "AVAILABLE":
            continue
        path = root / entry["relative_path"]
        if not path.is_file() or _sha256(path) != entry["sha256"]:
            raise IAPDLocalError(f"bundle integrity failed before upload: {entry['firm_id']}")
        object_key = f"iapd/{dataset_version}/objects/{entry['sha256']}.json.gz"
        published_entries[str(entry["firm_id"])]["object_key"] = object_key
        upload_jobs.append(
            (str(entry["firm_id"]), path, object_key, str(entry["sha256"]), path.stat().st_size)
        )

    previous_manifest = _read_r2_object(client, config.bucket, manifest_key)
    rollback_manifest_key = None
    if previous_manifest is not None:
        previous_bytes, previous_metadata = previous_manifest
        previous_hash = hashlib.sha256(previous_bytes).hexdigest()
        if previous_metadata.get("sha256") and previous_metadata["sha256"] != previous_hash:
            raise IAPDLocalError("active R2 manifest failed integrity validation")
        rollback_manifest_key = f"iapd/{dataset_version}/manifests/{previous_hash}.json"
        if not _head_matches(client, config.bucket, rollback_manifest_key, previous_hash, len(previous_bytes)):
            client.put_object(
                Bucket=config.bucket, Key=rollback_manifest_key, Body=previous_bytes,
                ContentType="application/json", CacheControl="private, max-age=31536000, immutable",
                Metadata={
                    "sha256": previous_hash,
                    "dataset-version": dataset_version,
                    "schema-version": MANIFEST_SCHEMA_VERSION,
                    "purpose": "rollback-manifest",
                },
            )
            if not _head_matches(client, config.bucket, rollback_manifest_key, previous_hash, len(previous_bytes)):
                raise IAPDLocalError("R2 rollback manifest verification failed")

    def upload_and_verify(job: tuple[str, Path, str, str, int]) -> bool:
        firm_id, path, object_key, expected_hash, size = job
        existed = _head_matches(
            client, config.bucket, object_key, expected_hash, size,
        )
        if existed and not force:
            uploaded = False
        else:
            with path.open("rb") as body:
                client.put_object(
                    Bucket=config.bucket, Key=object_key, Body=body,
                    ContentType="application/json", ContentEncoding="gzip",
                    CacheControl="private, max-age=300",
                    Metadata={
                        "sha256": expected_hash,
                        "dataset-version": dataset_version,
                        "schema-version": BUNDLE_SCHEMA_VERSION,
                    },
                )
            uploaded = True
        if not _head_matches(
            client, config.bucket, object_key, expected_hash, size,
        ):
            raise IAPDLocalError(f"R2 verification failed: {firm_id}")
        return uploaded

    updated = skipped = verified = 0
    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="iapd-r2")
    futures: list[Future[bool]] = []
    try:
        futures = [executor.submit(upload_and_verify, job) for job in upload_jobs]
        for future in as_completed(futures):
            if future.result():
                updated += 1
            else:
                skipped += 1
            verified += 1
    except BaseException:
        for future in futures:
            future.cancel()
        executor.shutdown(wait=True, cancel_futures=True)
        raise
    else:
        executor.shutdown(wait=True)

    inserted = 0
    manifest_bytes = _canonical_json(published_manifest)
    manifest_hash = hashlib.sha256(manifest_bytes).hexdigest()
    manifest_exists = _head_matches(
        client, config.bucket, manifest_key, manifest_hash, len(manifest_bytes),
    )
    if force or not manifest_exists:
        client.put_object(
            Bucket=config.bucket, Key=manifest_key, Body=manifest_bytes,
            ContentType="application/json", CacheControl="private, max-age=60",
            Metadata={
                "sha256": manifest_hash,
                "dataset-version": dataset_version,
                "schema-version": MANIFEST_SCHEMA_VERSION,
            },
        )
        inserted = 1
    if not _head_matches(client, config.bucket, manifest_key, manifest_hash, len(manifest_bytes)):
        raise IAPDLocalError("R2 manifest activation verification failed")
    report = {
        "status": "success",
        "dataset_version": dataset_version,
        "account_id": config.account_id,
        "bucket": config.bucket,
        "force": force,
        "upload_workers": workers,
        "verified_bundles": verified,
        "uploaded_bundles": updated,
        "skipped_bundles": skipped,
        "manifest_uploaded": inserted,
        "manifest_key": manifest_key,
        "manifest_sha256": manifest_hash,
        "rollback_manifest_key": rollback_manifest_key,
    }
    if report_path is not None:
        _write_json_atomic(Path(report_path), report)
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description="Local-first IAPD and Cloudflare R2 tools")
    commands = parser.add_subparsers(dest="command", required=True)
    build = commands.add_parser("build-store")
    build.add_argument("--source-zip", type=Path, required=True)
    build.add_argument("--source-url", required=True)
    build.add_argument("--snapshot-date", type=date.fromisoformat, required=True)
    build.add_argument("--dataset-version", required=True)
    build.add_argument("--output-root", type=Path)
    build.add_argument("--expected-current-links", type=int)
    build.add_argument("--firm-source-duckdb", type=Path)
    build.add_argument("--firm-table")
    bundles = commands.add_parser("build-bundles")
    bundles.add_argument("--dataset-version", required=True)
    bundles.add_argument("--local-root", type=Path)
    bundles.add_argument("--output-root", type=Path)
    bundles.add_argument("--firm-source-duckdb", type=Path, required=True)
    bundles.add_argument("--firm-table", required=True)
    publish = commands.add_parser("publish-r2")
    publish.add_argument("--manifest", type=Path, required=True)
    publish.add_argument("--report-path", type=Path)
    publish.add_argument("--force", action="store_true", help="Re-upload every verified bundle and activation manifest")
    publish.add_argument(
        "--workers", type=int, default=int(os.getenv("IAPD_R2_UPLOAD_WORKERS", "16")),
        help="Bounded concurrent R2 uploads (1-64; default: 16)",
    )
    args = parser.parse_args()
    if args.command == "build-store":
        if bool(args.firm_source_duckdb) != bool(args.firm_table):
            parser.error("--firm-source-duckdb and --firm-table must be provided together")
        dashboard_firms = load_firm_ids(
            source_duckdb=args.firm_source_duckdb, table_name=args.firm_table,
        ) if args.firm_source_duckdb else None
        result = build_local_store(
            source_zip=args.source_zip, source_url=args.source_url,
            snapshot_date=args.snapshot_date, dataset_version=args.dataset_version,
            output_root=args.output_root,
            expected_current_links=args.expected_current_links,
            dashboard_firm_ids=dashboard_firms,
        )
    elif args.command == "build-bundles":
        firm_ids = load_firm_ids(
            source_duckdb=args.firm_source_duckdb, table_name=args.firm_table,
        )
        result = generate_firm_bundles(
            dataset_version=args.dataset_version, local_root=args.local_root,
            output_root=args.output_root, firm_ids=firm_ids,
        )
    else:
        result = publish_bundles_to_r2(
            manifest_path=args.manifest, report_path=args.report_path,
            force=args.force, workers=args.workers,
        )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()

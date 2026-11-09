"""Read-only production publication gate. Never repairs schema or migration state."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
from typing import Mapping
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_TABLES = (
    "dataset_versions", "firms", "firm_scores", "iapd_feed_runs",
    "iapd_live_batches", "iapd_live_jobs", "iapd_live_captures",
    "iapd_individual_live_enrichments", "iapd_individual_reconciliations",
    "iapd_manual_review_queue", "iapd_snapshot_comparisons",
    "iapd_firm_change_summaries",
)
DATABASE_URL_KEYS = ("DATABASE_URL", "PUBLISHER_DATABASE_URL")
FINGERPRINT_PATTERN = re.compile(r"[0-9a-f]{64}")


def database_identity(url: str) -> dict:
    parsed = urlsplit(url)
    if parsed.scheme not in {"postgres", "postgresql"} or not parsed.hostname or not parsed.path.strip("/"):
        raise ValueError("An explicit PostgreSQL database URL is required")
    host = parsed.hostname.lower().replace("-pooler.", ".")
    if host in {"localhost", "127.0.0.1", "::1"}:
        raise ValueError("Production refresh refuses a localhost database target")
    return {"host": host, "port": parsed.port or 5432, "database": parsed.path.lstrip("/"), "schema": "public"}


def database_fingerprint(identity: Mapping[str, object]) -> str:
    """Return a credential-free identifier for an approved database target."""
    payload = json.dumps(dict(identity), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def required_database_urls(environ: Mapping[str, str]) -> tuple[str, str]:
    missing = [key for key in DATABASE_URL_KEYS if not environ.get(key, "").strip()]
    if missing:
        raise ValueError("Production refresh requires explicit " + " and ".join(missing))
    return environ["DATABASE_URL"], environ["PUBLISHER_DATABASE_URL"]


def matching_database_identity(migration_url: str, publisher_url: str) -> dict:
    migration = database_identity(migration_url)
    publisher = database_identity(publisher_url)
    if migration != publisher:
        raise ValueError("Migration and publisher database identities differ; publication blocked")
    return migration


def validate_approved_fingerprint(identity: Mapping[str, object], expected: str) -> str:
    normalized = expected.strip().lower()
    if not FINGERPRINT_PATTERN.fullmatch(normalized):
        raise ValueError("SCM_PRODUCTION_DATABASE_FINGERPRINT must be a 64-character SHA-256 value")
    actual = database_fingerprint(identity)
    if not hmac.compare_digest(actual, normalized):
        raise ValueError("Database target does not match the approved production fingerprint")
    return actual


def expected_ledger(root: Path = ROOT) -> list[tuple[str, int]]:
    directory = root / "web" / "drizzle"
    entries = json.loads((directory / "meta" / "_journal.json").read_text())["entries"]
    return [(hashlib.sha256((directory / f'{entry["tag"]}.sql').read_bytes()).hexdigest(), entry["when"]) for entry in entries]


def validate_ledger(actual, expected):
    if [(str(row[0]), int(row[1])) for row in actual] != expected:
        raise ValueError("Drizzle ledger hashes/order/timestamps differ from local migrations; publication blocked")


def preflight(*, migration_url: str, publisher_url: str, expected_fingerprint: str, root: Path = ROOT) -> dict:
    import psycopg
    migration = matching_database_identity(migration_url, publisher_url)
    fingerprint = validate_approved_fingerprint(migration, expected_fingerprint)
    expected = expected_ledger(root)
    checks = []
    for name, url in (("DATABASE_URL", migration_url), ("PUBLISHER_DATABASE_URL", publisher_url)):
        with psycopg.connect(url, connect_timeout=15, options="-c default_transaction_read_only=on") as connection:
            connection.execute("SET LOCAL statement_timeout = '15s'")
            database, schema = connection.execute("select current_database(),current_schema()").fetchone()
            if database != migration["database"] or schema != "public":
                raise ValueError("Connected database/schema does not match the approved target")
            ledger = connection.execute("select hash,created_at from drizzle.__drizzle_migrations order by id").fetchall()
            validate_ledger(ledger, expected)
            missing = [table for table in REQUIRED_TABLES if connection.execute("select to_regclass(%s)", (f"public.{table}",)).fetchone()[0] is None]
            if missing:
                raise ValueError("Missing production tables: " + ", ".join(missing))
            checks.append({"env_var": name, **migration, "ledger_rows": len(ledger)})
    return {
        "status": "passed",
        "read_only": True,
        "database_target": {**migration, "fingerprint": fingerprint},
        "targets": checks,
        "required_tables": list(REQUIRED_TABLES),
    }


def discover_sources() -> dict:
    """Discover public links only; do not download feeds or write import records."""
    from src.download import get_latest_url, get_discovery_status
    from src.iapd_recovery import discover_compilation
    result = {}
    try:
        url = get_latest_url()
        status = get_discovery_status()
        result["sec"] = {"url": url, "fallback_used": bool(status.get("fallback_used"))}
    except Exception as error:
        result["sec"] = {"status": "unavailable", "error_type": type(error).__name__}
    try:
        dates = discover_compilation()
        result["iapd"] = {"status": "available" if dates else "unavailable", "dates": [str(day) for day in dates]}
    except Exception as error:
        result["iapd"] = {"status": "unavailable", "error_type": type(error).__name__}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--print-target-fingerprint", action="store_true")
    args = parser.parse_args()
    try:
        migration, publisher = required_database_urls(os.environ)
        identity = matching_database_identity(migration, publisher)
        if args.print_target_fingerprint:
            print(json.dumps({"database_target": {**identity, "fingerprint": database_fingerprint(identity)}}, indent=2))
            return
        approved_fingerprint = os.environ.get("SCM_PRODUCTION_DATABASE_FINGERPRINT", "")
        result = preflight(
            migration_url=migration,
            publisher_url=publisher,
            expected_fingerprint=approved_fingerprint,
        )
        result["mode"] = "dry_run" if args.dry_run else "preflight"
        result["stages"] = ["SEC refresh", "dashboard publication", "ADV publication", "IAPD discovery/import", "snapshot comparison", "compact publication", "R2 bundles", "bounded live batch"]
        result["iapd_live_limit"] = int(os.getenv("IAPD_LIVE_BATCH_SIZE", "25"))
        result["r2_configured"] = all(os.getenv(key) for key in ("CLOUDFLARE_R2_ACCOUNT_ID", "CLOUDFLARE_R2_ACCESS_KEY_ID", "CLOUDFLARE_R2_SECRET_ACCESS_KEY", "CLOUDFLARE_R2_BUCKET"))
        result["source_discovery"] = discover_sources()
        sec = result["source_discovery"]["sec"]
        if sec.get("fallback_used") or not sec.get("url"):
            result["status"] = "blocked"
            result["reason"] = "SEC discovery did not confirm the current official feed; fallback publication is blocked"
        print(json.dumps(result, indent=2))
        if result["status"] == "blocked":
            raise SystemExit(1)
    except Exception as error:
        # Connection errors can contain connection parameters; never echo their text.
        message = str(error) if isinstance(error, ValueError) else type(error).__name__
        print(json.dumps({"status": "blocked", "reason": message}))
        raise SystemExit(1)


if __name__ == "__main__":
    main()

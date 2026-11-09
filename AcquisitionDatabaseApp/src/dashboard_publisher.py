"""Publish protected local production outputs into the dashboard database.

The publisher is intentionally one-way: DuckDB/SQLite are read-only inputs and
workflow tables in PostgreSQL are never deleted or overwritten.
"""
from __future__ import annotations

import argparse
import csv
import codecs
import io
import json
import sqlite3
import zipfile
from pathlib import Path
from datetime import datetime, timezone
from typing import Any

import duckdb

from src.config import settings
from src.gold_eligibility import SCORE_VERSION
from src.gold_v1 import gold_v1_table_name


def _json(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, (list, dict)):
        return value
    try:
        return json.loads(str(value))
    except (TypeError, ValueError, json.JSONDecodeError):
        return value


def _clean(value: Any) -> Any:
    if value is None:
        return None
    try:
        if value != value:
            return None
    except Exception:
        pass
    return _json(value)


def _bool(value: Any) -> bool | None:
    value = _clean(value)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        if value.strip().lower() in {"true", "t", "yes", "y", "1"}:
            return True
        if value.strip().lower() in {"false", "f", "no", "n", "0", ""}:
            return False
    try:
        return bool(float(value))
    except (TypeError, ValueError):
        return None


def _rows(path: str, table: str) -> tuple[list[str], list[tuple[Any, ...]]]:
    with duckdb.connect(path, read_only=True) as conn:
        result = conn.execute(f'SELECT * FROM "{table}"')
        return [d[0] for d in result.description], [tuple(_clean(v) for v in row) for row in result.fetchall()]


OFFICE_FIELDS = {
    "main_office_street_address_1": "Main Office Street Address 1",
    "main_office_street_address_2": "Main Office Street Address 2",
    "main_office_city": "Main Office City",
    "main_office_state": "Main Office State",
    "main_office_country": "Main Office Country",
    "main_office_phone": "Main Office Telephone Number",
    "main_office_postal_code": "Main Office Postal Code",
}


def _bronze_offices(zip_path: Path, dataset_version: str) -> dict[str, dict[str, Any]]:
    """Read exact-dataset SEC office facts without altering any analytical artifacts."""
    if zip_path.stem != dataset_version:
        raise ValueError("Office source ZIP must match the requested dataset version")
    result = {}
    with zipfile.ZipFile(zip_path) as archive:
        members = [n for n in archive.namelist() if n.lower().endswith('.csv')]
        if len(members) != 1:
            raise ValueError("Expected one unambiguous SEC roster CSV")
        if archive.getinfo(members[0]).file_size > 512 * 1024 * 1024:
            raise ValueError("Office roster exceeds the extraction size limit")
        encoding = 'utf-8-sig'
        decoder = codecs.getincrementaldecoder(encoding)()
        try:
            with archive.open(members[0]) as raw:
                while chunk := raw.read(65536):
                    decoder.decode(chunk)
                decoder.decode(b'', final=True)
        except UnicodeDecodeError:
            encoding = 'cp1252'
        with archive.open(members[0]) as raw:
            reader = csv.DictReader(io.TextIOWrapper(raw, encoding=encoding, newline=''))
            if not {'Organization CRD#', *OFFICE_FIELDS.values()}.issubset(reader.fieldnames or []):
                raise ValueError("SEC roster is missing required office source columns")
            for row in reader:
                crd = str(row.get('Organization CRD#') or '').strip()
                if not crd.isdigit() or crd in result:
                    raise ValueError("Missing, invalid, or duplicate office CRD")
                result[crd] = {key: (row.get(source) or '').strip() or None for key, source in OFFICE_FIELDS.items()}
        # Reading the entire member above also verifies its ZIP CRC.
    return result


def _main_offices(path: str, dataset_version: str, bronze_zip: Path | None = None) -> dict[str, dict[str, Any]]:
    """Read main-office facts when the protected Silver office table exists."""
    table = f"silver_firm_offices_{dataset_version}"
    with duckdb.connect(path, read_only=True) as conn:
        tables = {row[0] for row in conn.execute("SHOW TABLES").fetchall()}
        if table not in tables:
            return _bronze_offices(bronze_zip, dataset_version) if bronze_zip and bronze_zip.exists() else {}
        rows = conn.execute(
            f'''SELECT firm_id, street_address_1, street_address_2, city, state, country, telephone, postal_code
                FROM "{table}" WHERE office_type = 'MAIN' ORDER BY firm_id'''
        ).fetchall()
    result: dict[str, dict[str, Any]] = {}
    for row in rows:
        result.setdefault(str(row[0]), {
            "main_office_street_address_1": _clean(row[1]),
            "main_office_street_address_2": _clean(row[2]),
            "main_office_city": _clean(row[3]),
            "main_office_state": _clean(row[4]),
            "main_office_country": _clean(row[5]),
            "main_office_phone": _clean(row[6]),
            "main_office_postal_code": _clean(row[7]),
        })
    return result


def _upsert(conn: Any, table: str, columns: list[str], values: tuple[Any, ...], conflict: list[str], updates: list[str]) -> None:
    cols = ",".join(columns)
    placeholders = ",".join("%s" for _ in columns)
    assignments = ",".join(f"{c}=EXCLUDED.{c}" for c in updates)
    sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) ON CONFLICT ({','.join(conflict)}) DO UPDATE SET {assignments}"
    conn.execute(sql, values)


def _source_score_version(columns: list[str], rows: list[tuple[Any, ...]]) -> str:
    """Return the one score version carried by Gold, rejecting mixed output."""
    if "score_version" not in columns:
        return SCORE_VERSION
    position = columns.index("score_version")
    versions = {
        str(row[position]).strip()
        for row in rows
        if row[position] is not None and str(row[position]).strip()
    }
    if len(versions) > 1:
        raise RuntimeError(f"Protected Gold contains mixed score versions: {sorted(versions)}")
    return next(iter(versions), SCORE_VERSION)


def _dataset_date(dataset_version: str) -> str | None:
    if dataset_version.startswith("iapdfirm") and len(dataset_version) == 16:
        value = dataset_version.removeprefix("iapdfirm")
        return f"{value[:4]}-{value[4:6]}-{value[6:8]}"
    return dataset_version[2:] if dataset_version.startswith("ia") else None


def _firm_universe_counts(columns: list[str], rows: list[tuple[Any, ...]]) -> dict[str, int | None]:
    index = {column: columns.index(column) for column in columns}
    has_registration = "is_registered" in index
    return {
        "source_firm_count": len(rows),
        "registered_firm_count": sum(_bool(row[index["is_registered"]]) is True for row in rows) if has_registration else None,
        "era_only_firm_count": sum(_bool(row[index["is_era_only"]]) is True for row in rows) if "is_era_only" in index else None,
        "dual_registered_firm_count": sum(_bool(row[index["is_dual_registered"]]) is True for row in rows) if "is_dual_registered" in index else None,
        "acquisition_target_count": sum(
            _bool(row[index["is_registered"]]) is True
            and str(row[index["priority_category"]]) in {"PRIORITY_A", "PRIORITY_B", "PRIORITY_C"}
            for row in rows
        ) if has_registration and "priority_category" in index else None,
    }


def publish(dataset_version: str, database_url: str) -> dict[str, Any]:
    import psycopg

    table = gold_v1_table_name(dataset_version)
    columns, rows = _rows(str(settings.DUCKDB_FILE), table)
    if not rows or "firm_id" not in columns:
        raise RuntimeError(f"Protected Gold V1 table is empty or invalid: {table}")
    index = {column: columns.index(column) for column in columns}
    score_version = _source_score_version(columns, rows)
    offices = _main_offices(str(settings.DUCKDB_FILE), dataset_version, settings.RAW_DIR / f"{dataset_version}.zip")
    priorities = {str(row[index["priority_category"]]): 0 for row in rows if "priority_category" in index}
    for row in rows:
        if "priority_category" in index:
            key = str(row[index["priority_category"]])
            priorities[key] = priorities.get(key, 0) + 1
    universe_counts = _firm_universe_counts(columns, rows)
    now = datetime.now(timezone.utc)
    counts = {"firms": 0, "facts": 0, "scores": 0, "research": 0, "sources": 0}
    with sqlite3.connect(settings.BASE_DIR / "research.db") as research_db:
        research_db.row_factory = sqlite3.Row
        research = research_db.execute("SELECT * FROM target_research WHERE dataset_version = ?", (dataset_version,)).fetchall()
        sources = research_db.execute("""SELECT * FROM target_research_sources
            WHERE dataset_version = ?""", (dataset_version,)).fetchall()
    with sqlite3.connect(settings.DB_FILE) as operations_db:
        operations_db.row_factory = sqlite3.Row
        table_names = {row[0] for row in operations_db.execute("select name from sqlite_master where type='table'")}
        pipeline_runs = operations_db.execute("select * from pipeline_runs order by started_at desc").fetchall() if "pipeline_runs" in table_names else []
        operational_alerts = operations_db.execute("select * from operational_alerts order by created_at desc").fetchall() if "operational_alerts" in table_names else []
        backups = operations_db.execute("select * from backups order by created_at desc").fetchall() if "backups" in table_names else []
    with psycopg.connect(database_url) as conn:
        # Keep the existing all-or-nothing transaction, but pipeline the
        # independent per-row upserts.  This preserves every SQL statement,
        # conflict rule, and source mapping while avoiding one network
        # round-trip per firm when the destination is remote PostgreSQL.
        with conn.transaction(), conn.pipeline():
            conn.execute("""INSERT INTO dataset_versions
                (dataset_version,dataset_date,score_version,silver_rows,gold_rows,source_firm_count,registered_firm_count,era_only_firm_count,dual_registered_firm_count,acquisition_target_count,priority_counts,published_at,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (dataset_version) DO UPDATE SET dataset_date=EXCLUDED.dataset_date,
                score_version=EXCLUDED.score_version,silver_rows=EXCLUDED.silver_rows,gold_rows=EXCLUDED.gold_rows,
                source_firm_count=EXCLUDED.source_firm_count,registered_firm_count=EXCLUDED.registered_firm_count,
                era_only_firm_count=EXCLUDED.era_only_firm_count,dual_registered_firm_count=EXCLUDED.dual_registered_firm_count,
                acquisition_target_count=EXCLUDED.acquisition_target_count,priority_counts=EXCLUDED.priority_counts,
                published_at=EXCLUDED.published_at,updated_at=EXCLUDED.updated_at""",
                (dataset_version, _dataset_date(dataset_version), score_version, len(rows), len(rows),
                 universe_counts["source_firm_count"], universe_counts["registered_firm_count"],
                 universe_counts["era_only_firm_count"], universe_counts["dual_registered_firm_count"],
                 universe_counts["acquisition_target_count"],
                 json.dumps(priorities), now, now, now))
            for row in rows:
                firm_id = str(row[index["firm_id"]])
                base = (firm_id, dataset_version, now, now)
                def val(name: str) -> Any: return row[index[name]] if name in index else None
                conn.execute("""INSERT INTO firms (firm_id,dataset_version,name,primary_business_name,sec_number,website_address,organization_state,sec_region,sec_current_status,canonical_population_source,population_classification,is_registered,is_sec_registered,is_state_registered,is_era_only,has_era_relationship,is_dual_registered,registration_review_required,created_at,updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (firm_id,dataset_version) DO UPDATE SET name=EXCLUDED.name,primary_business_name=EXCLUDED.primary_business_name,sec_number=EXCLUDED.sec_number,website_address=EXCLUDED.website_address,organization_state=EXCLUDED.organization_state,sec_region=EXCLUDED.sec_region,sec_current_status=EXCLUDED.sec_current_status,canonical_population_source=EXCLUDED.canonical_population_source,population_classification=EXCLUDED.population_classification,is_registered=EXCLUDED.is_registered,is_sec_registered=EXCLUDED.is_sec_registered,is_state_registered=EXCLUDED.is_state_registered,is_era_only=EXCLUDED.is_era_only,has_era_relationship=EXCLUDED.has_era_relationship,is_dual_registered=EXCLUDED.is_dual_registered,registration_review_required=EXCLUDED.registration_review_required,updated_at=EXCLUDED.updated_at""",
                    base[:2] + (val("name"), val("primary_business_name"), val("sec_number"), val("website_address"), val("organization_state"), val("sec_region"), val("sec_current_status"),val("canonical_population_source"),val("population_classification"),_bool(val("is_registered")),_bool(val("is_sec_registered")),_bool(val("is_state_registered")),_bool(val("is_era_only")),_bool(val("has_era_relationship")),_bool(val("is_dual_registered")),_bool(val("registration_review_required")),now,now))
                office = offices.get(firm_id, {})
                conn.execute("""INSERT INTO firm_facts (firm_id,dataset_version,total_aum,discretionary_aum,non_discretionary_aum,total_account_count,average_account_size,individual_hnw_share,employee_count,advisory_employee_count,state_iar_count,has_item_11_disclosure,regulatory_review_flag,main_office_street_address_1,main_office_street_address_2,main_office_city,main_office_state,main_office_country,main_office_phone,main_office_postal_code,created_at,updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (firm_id,dataset_version) DO UPDATE SET total_aum=EXCLUDED.total_aum,discretionary_aum=EXCLUDED.discretionary_aum,non_discretionary_aum=EXCLUDED.non_discretionary_aum,total_account_count=EXCLUDED.total_account_count,average_account_size=EXCLUDED.average_account_size,individual_hnw_share=EXCLUDED.individual_hnw_share,employee_count=EXCLUDED.employee_count,advisory_employee_count=EXCLUDED.advisory_employee_count,state_iar_count=EXCLUDED.state_iar_count,has_item_11_disclosure=EXCLUDED.has_item_11_disclosure,regulatory_review_flag=EXCLUDED.regulatory_review_flag,main_office_street_address_1=EXCLUDED.main_office_street_address_1,main_office_street_address_2=EXCLUDED.main_office_street_address_2,main_office_city=EXCLUDED.main_office_city,main_office_state=EXCLUDED.main_office_state,main_office_country=EXCLUDED.main_office_country,main_office_phone=EXCLUDED.main_office_phone,main_office_postal_code=EXCLUDED.main_office_postal_code,updated_at=EXCLUDED.updated_at""",
                    (firm_id,dataset_version,val("total_aum"),val("discretionary_aum"),val("non_discretionary_aum"),val("total_account_count"),val("average_account_size"),val("individual_hnw_share"),val("employee_count"),val("advisory_employee_count"),val("state_iar_count"),_bool(val("has_item_11_disclosure")),_bool(val("regulatory_review_flag")),office.get("main_office_street_address_1"),office.get("main_office_street_address_2"),office.get("main_office_city"),office.get("main_office_state"),office.get("main_office_country"),office.get("main_office_phone"),office.get("main_office_postal_code"),now,now))
                conn.execute("""INSERT INTO firm_scores (firm_id,dataset_version,acquisition_score,priority_category,priority_readiness,review_required,component_scores,reason_codes,created_at,updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (firm_id,dataset_version) DO UPDATE SET acquisition_score=EXCLUDED.acquisition_score,priority_category=EXCLUDED.priority_category,priority_readiness=EXCLUDED.priority_readiness,review_required=EXCLUDED.review_required,component_scores=EXCLUDED.component_scores,reason_codes=EXCLUDED.reason_codes,updated_at=EXCLUDED.updated_at""",
                    (firm_id,dataset_version,val("acquisition_score"),val("priority_category"),val("priority_readiness"),val("review_required"),json.dumps({k:val(k) for k in ("aum_fit_score","discretionary_fit_score","client_fit_score","account_practice_fit_score","practice_complexity_score","advisory_model_fit_score","regulatory_quality_score")}),json.dumps(_json(val("reason_codes"))),now,now))
                counts["firms"] += 1; counts["facts"] += 1; counts["scores"] += 1
                if val("population_classification") != "ERA_ONLY":
                    conn.execute("""INSERT INTO outreach_targets (firm_id,dataset_version,status,created_at,updated_at)
                        VALUES (%s,%s,'NOT_RESEARCHED',%s,%s) ON CONFLICT (firm_id,dataset_version) DO NOTHING""",
                        (firm_id, dataset_version, now, now))
            for item in research:
                conn.execute("""INSERT INTO firm_research (firm_id,dataset_version,research_status,research_owner,founder_name,founder_role,ownership_type,ownership_summary,succession_readiness_assessment,investment_philosophy,primary_custodian,strategic_fit_assessment,transition_feasibility,integration_risks,created_at,updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (firm_id,dataset_version) DO NOTHING""",
                    tuple(item[k] for k in ("firm_id","dataset_version","research_status","research_owner","founder_name","founder_role","ownership_type","ownership_summary","succession_readiness_assessment","investment_philosophy","primary_custodian","strategic_fit_assessment","transition_feasibility","integration_risks")) + (now,now,))
                counts["research"] += 1
            for item in sources:
                conn.execute("""INSERT INTO research_sources (source_id,firm_id,dataset_version,source_type,source_url,source_title,source_authority,accessed_at,retrieval_status,content_hash,field_supported,source_notes,created_at,updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (source_id) DO UPDATE SET source_url=EXCLUDED.source_url,source_title=EXCLUDED.source_title,retrieval_status=EXCLUDED.retrieval_status,content_hash=EXCLUDED.content_hash,source_notes=EXCLUDED.source_notes,updated_at=EXCLUDED.updated_at""",
                    tuple(item[k] for k in ("source_id","firm_id","dataset_version","source_type","source_url","source_title","source_authority","accessed_at","retrieval_status","content_hash","field_supported","source_notes")) + (now,now,))
                counts["sources"] += 1
            # Carry only already-confirmed seller-intent state forward to the
            # new dataset. UNKNOWN firms need no row. This preserves durable
            # business-development evidence without allowing SEC publication
            # to infer or overwrite intent.
            conn.execute("""INSERT INTO seller_intent_current
                (firm_id,dataset_version,status,confidence,primary_evidence_id,confirmed_by,confirmed_at,last_reviewed_at,notes,created_at,updated_at)
                SELECT f.firm_id,%s,previous.status,previous.confidence,previous.primary_evidence_id,previous.confirmed_by,previous.confirmed_at,previous.last_reviewed_at,previous.notes,%s,%s
                FROM firms f JOIN LATERAL (
                  SELECT si.* FROM seller_intent_current si
                  WHERE si.firm_id=f.firm_id AND si.dataset_version<>%s
                  ORDER BY si.updated_at DESC LIMIT 1
                ) previous ON true
                WHERE f.dataset_version=%s
                ON CONFLICT (firm_id,dataset_version) DO NOTHING""",
                (dataset_version, now, now, dataset_version, dataset_version))
            for item in pipeline_runs:
                conn.execute("""INSERT INTO pipeline_runs (run_id,dataset_version,status,started_at,completed_at,duration_seconds,details)
                    VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (run_id) DO UPDATE SET status=EXCLUDED.status,completed_at=EXCLUDED.completed_at,duration_seconds=EXCLUDED.duration_seconds,details=EXCLUDED.details""",
                    (item["run_id"], item["dataset_version"], item["status"], item["started_at"], item["completed_at"], item["execution_duration_seconds"], json.dumps(dict(item))))
            for item in operational_alerts:
                conn.execute("""INSERT INTO alerts (alert_id,event_type,severity,message,created_at,acknowledged_at)
                    VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (alert_id) DO NOTHING""",
                    (str(item["alert_id"]), item["event_type"], item["severity"], item["message"], item["created_at"], item["acknowledged_at"]))
            for item in backups:
                conn.execute("""INSERT INTO backup_metadata (backup_id,dataset_version,created_at,status,manifest)
                    VALUES (%s,%s,%s,%s,%s) ON CONFLICT (backup_id) DO UPDATE SET status=EXCLUDED.status,manifest=EXCLUDED.manifest""",
                    (item["backup_id"], item["dataset_version"], item["created_at"], item["status"], item["manifest_json"]))
    return {"dataset_version": dataset_version, "published": counts, "priority_counts": priorities}


def publish_office_contacts(dataset_version: str, database_url: str) -> dict[str, Any]:
    """Publish office facts only, with exact dataset/CRD reconciliation before commit."""
    import psycopg

    source = settings.RAW_DIR / f"{dataset_version}.zip"
    offices = _main_offices(str(settings.DUCKDB_FILE), dataset_version, source)
    if not offices:
        raise ValueError("No verified office source available")
    fields = list(OFFICE_FIELDS)
    with psycopg.connect(database_url) as conn:
        with conn.transaction():
            conn.execute("SET LOCAL lock_timeout = '10s'")
            active = conn.execute("SELECT dataset_version FROM dataset_versions ORDER BY published_at DESC, dataset_version DESC LIMIT 1").fetchone()
            if not active or active[0] != dataset_version:
                raise ValueError("Office publication requires the active dashboard dataset")
            ids = {str(row[0]) for row in conn.execute("SELECT firm_id FROM firm_facts WHERE dataset_version=%s FOR UPDATE", (dataset_version,))}
            if ids != set(offices):
                raise ValueError("Office source CRDs do not exactly match the serving dataset")
            conn.execute("CREATE TEMP TABLE office_publish (firm_id text PRIMARY KEY, " + ','.join(f'{key} text' for key in fields) + ") ON COMMIT DROP")
            with conn.cursor().copy("COPY office_publish FROM STDIN") as copy:
                for crd, office in sorted(offices.items()):
                    copy.write_row((crd, *(office.get(key) for key in fields)))
            assignment = ','.join(f'{key}=o.{key}' for key in fields)
            changed = conn.execute(f"""UPDATE firm_facts f SET {assignment},updated_at=now()
                FROM office_publish o WHERE f.firm_id=o.firm_id AND f.dataset_version=%s
                AND ROW({','.join('f.'+key for key in fields)}) IS DISTINCT FROM ROW({','.join('o.'+key for key in fields)})""", (dataset_version,)).rowcount
            conn.execute("DROP TABLE pg_temp.office_publish")
    return {"dataset_version":dataset_version,"matched":len(offices),"updated":changed,"unchanged":len(offices)-changed}


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("publish", "publish-offices"):
        command = sub.add_parser(name)
        command.add_argument("--dataset-version", required=True)
        command.add_argument("--database-url", required=True)
    args = parser.parse_args()
    action = publish_office_contacts if args.command == "publish-offices" else publish
    print(json.dumps(action(args.dataset_version, args.database_url), indent=2, default=str))


if __name__ == "__main__":
    main()

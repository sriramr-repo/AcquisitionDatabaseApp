"""Publish protected local production outputs into the dashboard database.

The publisher is intentionally one-way: DuckDB/SQLite are read-only inputs and
workflow tables in PostgreSQL are never deleted or overwritten.
"""
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from typing import Any

import duckdb

from src.config import settings
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


def _upsert(conn: Any, table: str, columns: list[str], values: tuple[Any, ...], conflict: list[str], updates: list[str]) -> None:
    cols = ",".join(columns)
    placeholders = ",".join("%s" for _ in columns)
    assignments = ",".join(f"{c}=EXCLUDED.{c}" for c in updates)
    sql = f"INSERT INTO {table} ({cols}) VALUES ({placeholders}) ON CONFLICT ({','.join(conflict)}) DO UPDATE SET {assignments}"
    conn.execute(sql, values)


def publish(dataset_version: str, database_url: str) -> dict[str, Any]:
    import psycopg

    table = gold_v1_table_name(dataset_version)
    columns, rows = _rows(str(settings.DUCKDB_FILE), table)
    if not rows or "firm_id" not in columns:
        raise RuntimeError(f"Protected Gold V1 table is empty or invalid: {table}")
    index = {column: columns.index(column) for column in columns}
    priorities = {str(row[index["priority_category"]]): 0 for row in rows if "priority_category" in index}
    for row in rows:
        if "priority_category" in index:
            key = str(row[index["priority_category"]])
            priorities[key] = priorities.get(key, 0) + 1
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
        with conn.transaction():
            conn.execute("""INSERT INTO dataset_versions
                (dataset_version,dataset_date,score_version,silver_rows,gold_rows,priority_counts,published_at,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (dataset_version) DO UPDATE SET dataset_date=EXCLUDED.dataset_date,
                score_version=EXCLUDED.score_version,silver_rows=EXCLUDED.silver_rows,gold_rows=EXCLUDED.gold_rows,
                priority_counts=EXCLUDED.priority_counts,published_at=EXCLUDED.published_at,updated_at=EXCLUDED.updated_at""",
                (dataset_version, dataset_version[2:], "SCM_ACQUISITION_V1", len(rows), len(rows), json.dumps(priorities), now, now, now))
            for row in rows:
                firm_id = str(row[index["firm_id"]])
                base = (firm_id, dataset_version, now, now)
                def val(name: str) -> Any: return row[index[name]] if name in index else None
                conn.execute("""INSERT INTO firms (firm_id,dataset_version,name,primary_business_name,website_address,organization_state,sec_region,sec_current_status,created_at,updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (firm_id,dataset_version) DO UPDATE SET name=EXCLUDED.name,primary_business_name=EXCLUDED.primary_business_name,website_address=EXCLUDED.website_address,organization_state=EXCLUDED.organization_state,sec_region=EXCLUDED.sec_region,sec_current_status=EXCLUDED.sec_current_status,updated_at=EXCLUDED.updated_at""",
                    base[:2] + (val("name"), val("primary_business_name"), val("website_address"), val("organization_state"), val("sec_region"), val("sec_current_status"), now, now))
                conn.execute("""INSERT INTO firm_facts (firm_id,dataset_version,total_aum,discretionary_aum,non_discretionary_aum,total_account_count,average_account_size,individual_hnw_share,employee_count,advisory_employee_count,state_iar_count,has_item_11_disclosure,regulatory_review_flag,created_at,updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (firm_id,dataset_version) DO UPDATE SET total_aum=EXCLUDED.total_aum,discretionary_aum=EXCLUDED.discretionary_aum,non_discretionary_aum=EXCLUDED.non_discretionary_aum,total_account_count=EXCLUDED.total_account_count,average_account_size=EXCLUDED.average_account_size,individual_hnw_share=EXCLUDED.individual_hnw_share,employee_count=EXCLUDED.employee_count,advisory_employee_count=EXCLUDED.advisory_employee_count,state_iar_count=EXCLUDED.state_iar_count,has_item_11_disclosure=EXCLUDED.has_item_11_disclosure,regulatory_review_flag=EXCLUDED.regulatory_review_flag,updated_at=EXCLUDED.updated_at""",
                    (firm_id,dataset_version,val("total_aum"),val("discretionary_aum"),val("non_discretionary_aum"),val("total_account_count"),val("average_account_size"),val("individual_hnw_share"),val("employee_count"),val("advisory_employee_count"),val("state_iar_count"),_bool(val("has_item_11_disclosure")),_bool(val("regulatory_review_flag")),now,now))
                conn.execute("""INSERT INTO firm_scores (firm_id,dataset_version,acquisition_score,priority_category,priority_readiness,review_required,component_scores,reason_codes,created_at,updated_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (firm_id,dataset_version) DO UPDATE SET acquisition_score=EXCLUDED.acquisition_score,priority_category=EXCLUDED.priority_category,priority_readiness=EXCLUDED.priority_readiness,review_required=EXCLUDED.review_required,component_scores=EXCLUDED.component_scores,reason_codes=EXCLUDED.reason_codes,updated_at=EXCLUDED.updated_at""",
                    (firm_id,dataset_version,val("acquisition_score"),val("priority_category"),val("priority_readiness"),val("review_required"),json.dumps({k:val(k) for k in ("aum_fit_score","discretionary_fit_score","client_fit_score","account_practice_fit_score","practice_complexity_score","advisory_model_fit_score","regulatory_quality_score")}),json.dumps(_json(val("reason_codes"))),now,now))
                counts["firms"] += 1; counts["facts"] += 1; counts["scores"] += 1
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


def main() -> None:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    command = sub.add_parser("publish")
    command.add_argument("--dataset-version", required=True)
    command.add_argument("--database-url", required=True)
    args = parser.parse_args()
    print(json.dumps(publish(args.dataset_version, args.database_url), indent=2, default=str))


if __name__ == "__main__":
    main()

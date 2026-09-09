"""Deterministic extraction of current Form ADV facts from the SEC IA bulk file.

This module does not score firms. It preserves source columns and null/zero
semantics so dashboard facts can always be traced back to Form ADV.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

PARSER_VERSION = "scm-adv-structured-v1"
IAPD_SEARCH_URL = "https://adviserinfo.sec.gov/"
CLIENT_LABELS = {
    "a": "Individuals (other than high net worth individuals)", "b": "High net worth individuals",
    "c": "Banking or thrift institutions", "d": "Investment companies", "e": "Business development companies",
    "f": "Pooled investment vehicles", "g": "Pension and profit sharing plans", "h": "Charitable organizations",
    "i": "State or municipal government entities", "j": "Other investment advisers", "k": "Insurance companies",
    "l": "Sovereign wealth funds and foreign official institutions", "m": "Corporations or other businesses", "n": "Other",
}
REGISTRATION_BASIS = {str(i): label for i, label in {
    1:"Large advisory firm", 2:"Mid-sized advisory firm", 4:"Principal office outside the United States",
    5:"Investment company adviser or subadviser", 6:"Business development company adviser", 7:"Pension consultant",
    8:"Related adviser", 9:"120-day adviser", 10:"Multi-state adviser", 11:"Internet adviser",
    12:"SEC exemptive order", 13:"No longer eligible for SEC registration",
}.items()}
COMPENSATION = {"1":"Percentage of AUM", "2":"Hourly charges", "3":"Subscription fees", "4":"Fixed fees", "5":"Commissions", "6":"Performance-based fees", "7":"Other"}
ACTIVITIES = {"1":"Financial planning", "2":"Portfolio management for individuals/small businesses", "3":"Portfolio management for investment companies", "4":"Portfolio management for pooled vehicles", "5":"Portfolio management for businesses/institutions", "6":"Pension consulting", "7":"Selection of other advisers", "8":"Periodicals/newsletters", "9":"Security ratings/pricing", "10":"Market timing", "11":"Educational seminars/workshops", "12":"Other"}


def parse_bool(value: Any) -> bool | None:
    if value is None or not str(value).strip(): return None
    normalized = str(value).strip().lower()
    if normalized in {"y", "yes", "true", "1", "x", "fewer than 5 clients"}: return True
    if normalized in {"n", "no", "false", "0"}: return False
    return None


def parse_number(value: Any, *, integer: bool = False) -> int | float | None:
    if value is None: return None
    normalized = re.sub(r"[$,\s]", "", str(value))
    if not normalized: return None
    try:
        number = float(normalized)
    except ValueError:
        return None
    return int(number) if integer else number


def _selected(row: dict[str, Any], prefix: str, labels: dict[str, str]) -> list[dict[str, str]]:
    result = []
    for code, label in labels.items():
        field = f"{prefix}({code})"
        if parse_bool(row.get(field)) is True:
            item = {"code": code, "label": label, "source_field": field}
            other_text = str(row.get(f"{field}-Other") or "").strip()
            if other_text:
                item["other_text"] = other_text
            result.append(item)
    return result


@dataclass(frozen=True)
class AdvRecord:
    filing: dict[str, Any]
    facts: dict[str, Any]
    client_categories: list[dict[str, Any]]


def extract_record(row: dict[str, Any], dataset_version: str) -> AdvRecord:
    firm_id = str(row.get("Organization CRD#") or "").strip()
    if not firm_id:
        raise ValueError("Organization CRD# is required")
    source_fields = {"source_type": "SEC_IA_BULK", "dataset_version": dataset_version, "parser_version": PARSER_VERSION}
    clients = []
    for code, label in CLIENT_LABELS.items():
        clients.append({
            "firm_id": firm_id, "dataset_version": dataset_version, "category_code": code, "category_label": label,
            "client_count": parse_number(row.get(f"5D({code})(1)"), integer=True),
            "fewer_than_five": parse_bool(row.get(f"5D({code})(2)")),
            "aum": parse_number(row.get(f"5D({code})(3)")),
            "other_description": row.get("5D(n)-Other") if code == "n" else None,
            "source_fields": {"client_count": f"5D({code})(1)", "fewer_than_five": f"5D({code})(2)", "aum": f"5D({code})(3)"},
        })
    filing = {
        "firm_id": firm_id, "dataset_version": dataset_version, "filing_date": row.get("Date Submitted"),
        "legal_name": row.get("Legal Name"), "sec_number": row.get("SEC#"),
        "iapd_search_url": IAPD_SEARCH_URL,
        "iapd_summary_url": f"https://adviserinfo.sec.gov/firm/summary/{firm_id}",
        "pdf_url": f"https://reports.adviserinfo.sec.gov/reports/ADV/{firm_id}/PDF/{firm_id}.pdf",
        "retrieval_status": "STRUCTURED_AVAILABLE", "identity_status": "SEC_BULK_CRD_MATCHED",
        "validation_status": "SEC_BULK_VALIDATED", "parser_version": PARSER_VERSION,
    }
    facts = {
        "firm_id": firm_id, "dataset_version": dataset_version,
        "item_1o_over_1b": parse_bool(row.get("1O")), "item_1o_asset_band": row.get("1O - If yes, approx. amount of assets") or None,
        "sec_registration_basis": _selected(row, "2A", REGISTRATION_BASIS),
        "succession_indicator": parse_bool(row.get("4A")), "succession_date": row.get("4B") or None,
        "employee_count": parse_number(row.get("5A"), integer=True), "advisory_employee_count": parse_number(row.get("5B(1)"), integer=True),
        "broker_dealer_rep_count": parse_number(row.get("5B(2)"), integer=True), "state_iar_count": parse_number(row.get("5B(3)"), integer=True),
        "other_adviser_iar_count": parse_number(row.get("5B(4)"), integer=True), "insurance_agent_count": parse_number(row.get("5B(5)"), integer=True),
        "solicitor_count": parse_number(row.get("5B(6)"), integer=True), "compensation_arrangements": _selected(row, "5E", COMPENSATION),
        "provides_continuous_management": parse_bool(row.get("5F(1)")), "discretionary_aum": parse_number(row.get("5F(2)(a)")),
        "non_discretionary_aum": parse_number(row.get("5F(2)(b)")), "total_aum": parse_number(row.get("5F(2)(c)")),
        "discretionary_account_count": parse_number(row.get("5F(2)(d)"), integer=True), "non_discretionary_account_count": parse_number(row.get("5F(2)(e)"), integer=True),
        "total_account_count": parse_number(row.get("5F(2)(f)"), integer=True), "non_us_client_aum": parse_number(row.get("5F(3)")),
        "advisory_activities": _selected(row, "5G", ACTIVITIES), "client_categories": clients,
        "sma_custodian_reporting_required": parse_bool(row.get("5K(4)")),
        "source_fields": source_fields,
    }
    return AdvRecord(filing, facts, clients)


def iter_bulk_records(zip_path: Path, dataset_version: str, firm_ids: set[str] | None = None) -> Iterable[AdvRecord]:
    with zipfile.ZipFile(zip_path) as archive:
        members = sorted(name for name in archive.namelist() if name.lower().endswith(".csv"))
        if not members: raise ValueError("SEC IA ZIP contains no CSV")
        with archive.open(members[0]) as raw:
            reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline=""))
            for row in reader:
                firm_id = str(row.get("Organization CRD#") or "").strip()
                if firm_ids is None or firm_id in firm_ids:
                    yield extract_record(row, dataset_version)


def document_hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def validate_pdf(payload: bytes, expected_crd: str) -> None:
    if not payload.startswith(b"%PDF-"): raise ValueError("ADV document is not a PDF")
    if len(payload) < 1024: raise ValueError("ADV PDF is unexpectedly small")
    if not expected_crd.isdigit(): raise ValueError("Expected CRD must be numeric")


def stable_custodian_id(firm_id: str, dataset_version: str, legal_name: str, source_hash: str) -> str:
    material = json.dumps([firm_id, dataset_version, legal_name.strip().upper(), source_hash], separators=(",", ":"))
    return hashlib.sha256(material.encode()).hexdigest()[:32]


def publish_bulk_facts(zip_path: Path, dataset_version: str, database_url: str, firm_ids: set[str] | None = None) -> dict[str, int]:
    """Upsert compact current-filing facts without touching scoring/workflow tables."""
    import psycopg
    from psycopg.types.json import Jsonb
    from src.fact_catalog import records as catalog_records

    now = datetime.now(timezone.utc)
    counts = {"catalog": 0, "filings": 0, "facts": 0}
    with psycopg.connect(database_url) as conn, conn.transaction(), conn.pipeline():
        for definition in catalog_records():
            columns = list(definition)
            conn.execute(
                f"INSERT INTO fact_definitions ({','.join(columns)},created_at,updated_at) VALUES ({','.join('%s' for _ in columns)},%s,%s) "
                "ON CONFLICT (field_key) DO UPDATE SET display_label=EXCLUDED.display_label,short_definition=EXCLUDED.short_definition,category=EXCLUDED.category,form_item=EXCLUDED.form_item,data_class=EXCLUDED.data_class,value_type=EXCLUDED.value_type,primary_source_type=EXCLUDED.primary_source_type,primary_source_field=EXCLUDED.primary_source_field,fallback_source_type=EXCLUDED.fallback_source_type,extraction_method=EXCLUDED.extraction_method,null_meaning=EXCLUDED.null_meaning,editable=EXCLUDED.editable,requires_evidence=EXCLUDED.requires_evidence,used_in_scoring=EXCLUDED.used_in_scoring,dashboard_section=EXCLUDED.dashboard_section,display_order=EXCLUDED.display_order,definition_version=EXCLUDED.definition_version,active=EXCLUDED.active,updated_at=EXCLUDED.updated_at",
                tuple(definition[column] for column in columns) + (now, now),
            )
            counts["catalog"] += 1
        for record in iter_bulk_records(zip_path, dataset_version, firm_ids):
            filing = record.filing
            conn.execute(
                """INSERT INTO adv_current_filings
                (firm_id,dataset_version,filing_date,legal_name,sec_number,iapd_search_url,iapd_summary_url,pdf_url,retrieval_status,identity_status,validation_status,parser_version,last_successful_at,created_at,updated_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (firm_id,dataset_version) DO UPDATE SET filing_date=EXCLUDED.filing_date,legal_name=EXCLUDED.legal_name,sec_number=EXCLUDED.sec_number,iapd_search_url=EXCLUDED.iapd_search_url,iapd_summary_url=EXCLUDED.iapd_summary_url,pdf_url=EXCLUDED.pdf_url,retrieval_status=EXCLUDED.retrieval_status,identity_status=EXCLUDED.identity_status,validation_status=EXCLUDED.validation_status,parser_version=EXCLUDED.parser_version,last_successful_at=EXCLUDED.last_successful_at,last_error=NULL,updated_at=EXCLUDED.updated_at""",
                (filing["firm_id"], filing["dataset_version"], filing["filing_date"], filing["legal_name"], filing["sec_number"], filing["iapd_search_url"], filing["iapd_summary_url"], filing["pdf_url"], filing["retrieval_status"], filing["identity_status"], filing["validation_status"], filing["parser_version"], now, now, now),
            )
            fact = record.facts
            fields = ["item_1o_over_1b","item_1o_asset_band","sec_registration_basis","succession_indicator","succession_date","employee_count","advisory_employee_count","broker_dealer_rep_count","state_iar_count","other_adviser_iar_count","insurance_agent_count","solicitor_count","compensation_arrangements","provides_continuous_management","discretionary_aum","non_discretionary_aum","total_aum","discretionary_account_count","non_discretionary_account_count","total_account_count","non_us_client_aum","advisory_activities","client_categories","sma_custodian_reporting_required","source_fields"]
            values = [Jsonb(fact[name]) if isinstance(fact[name], (list, dict)) else fact[name] for name in fields]
            conn.execute(
                f"INSERT INTO adv_firm_facts (firm_id,dataset_version,{','.join(fields)},created_at,updated_at) VALUES (%s,%s,{','.join('%s' for _ in fields)},%s,%s) ON CONFLICT (firm_id,dataset_version) DO UPDATE SET " + ",".join(f"{field}=EXCLUDED.{field}" for field in fields) + ",updated_at=EXCLUDED.updated_at",
                (fact["firm_id"], fact["dataset_version"], *values, now, now),
            )
            counts["filings"] += 1
            counts["facts"] += 1
    return counts


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(description="Publish current structured Form ADV facts")
    parser.add_argument("publish", nargs="?")
    parser.add_argument("--zip-path", type=Path, required=True)
    parser.add_argument("--dataset-version", required=True)
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--firm-id", action="append", dest="firm_ids")
    args = parser.parse_args()
    print(json.dumps(publish_bulk_facts(args.zip_path, args.dataset_version, args.database_url, set(args.firm_ids) if args.firm_ids else None), indent=2))


if __name__ == "__main__":
    main()

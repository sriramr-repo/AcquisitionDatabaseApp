"""Live IAPD fallback capture and reconciliation.

This module deliberately does not change the Form ADV firm master or the
monthly IAPD snapshot.  It captures a bounded public page through Firecrawl,
normalizes only defensible labelled values, and records the effective view
with field-level provenance for the dashboard.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from typing import Any

import requests

from src.iapd import _clean, _stable_id
from src.config import PROJECT_ROOT


PARSER_VERSION = "iapd-live-v1"
FIRECRAWL_URL = "https://api.firecrawl.dev/v2/scrape"
IAPD_INDIVIDUAL_URL = "https://adviserinfo.sec.gov/individual/summary/{crd}"


class IAPDLiveUnavailable(RuntimeError):
    """A live IAPD fallback cannot be retrieved or safely interpreted."""


def build_iapd_individual_url(individual_crd: str) -> str:
    return IAPD_INDIVIDUAL_URL.format(crd=individual_crd.strip())


def _labelled(markdown: str, *labels: str) -> str | None:
    for label in labels:
        pattern = rf"(?im)^\s*(?:\*\*)?{re.escape(label)}(?:\*\*)?\s*[:\-]\s*([^\n]+)"
        match = re.search(pattern, markdown)
        if match:
            return _clean(match.group(1).strip("* "))
    return None


def _first_url(markdown: str) -> str | None:
    match = re.search(r"https?://[^\s)>\]]+", markdown)
    return match.group(0).rstrip(".,;") if match else None


def normalize_iapd_live_markdown(markdown: str, *, expected_crd: str | None = None) -> dict[str, Any]:
    """Extract labelled values from a public IAPD page without guessing.

    The raw capture is retained separately; any field that is not explicitly
    labelled is left null rather than inferred from surrounding prose.
    """
    crd = _labelled(markdown, "Individual CRD", "CRD Number", "CRD")
    if crd:
        digits = re.search(r"\d+", crd)
        crd = digits.group(0) if digits else None
    if expected_crd and crd and crd != expected_crd:
        raise IAPDLiveUnavailable(f"Live IAPD page CRD {crd} does not match requested CRD {expected_crd}")
    crd = crd or expected_crd
    full_name = _labelled(markdown, "Representative Name", "Individual Name", "Name")
    phone = _labelled(markdown, "Phone Number", "Phone", "Business Phone")
    if phone is None:
        match = re.search(r"(?:\+?1[ .-]?)?\(?\d{3}\)?[ .-]\d{3}[ .-]\d{4}", markdown)
        phone = match.group(0) if match else None
    website = _labelled(markdown, "Website", "Web Address") or _first_url(markdown)
    address = _labelled(markdown, "Business Address", "Office Address", "Address")
    disclosures = _labelled(markdown, "Disclosure", "Disciplinary History", "Disclosure Summary")
    status = _labelled(markdown, "Registration Status", "Status")
    registration_date = _labelled(markdown, "Registration Date", "Status Date")
    employer_name = _labelled(markdown, "Current Employer", "Current Firm", "Employer")
    employer_crd = _labelled(markdown, "Current Employer CRD", "Firm CRD", "Organization CRD")
    if employer_crd:
        digits = re.search(r"\d+", employer_crd)
        employer_crd = digits.group(0) if digits else None
    branches = [line.strip(" -*") for line in re.findall(r"(?im)^\s*(?:branch|office)\s*[:\-]\s*(.+)$", markdown) if _clean(line)]
    fields = {
        "full_name": full_name, "individual_crd": crd,
        "current_employer_name": employer_name, "current_employer_crd": employer_crd,
        "business_address": address, "phone": phone, "website": website,
        "registration_status": status, "registration_date": registration_date,
        "branch_locations": branches, "disclosure_summary": disclosures,
    }
    populated = sum(value not in (None, [], "") for value in fields.values())
    confidence = "HIGH" if crd and populated >= 5 else "MEDIUM" if crd and populated >= 2 else "LOW"
    return {"fields": fields, "confidence": confidence, "partial": populated < 5}


def _hash(payload: Any) -> str:
    return hashlib.sha256(json.dumps(payload, sort_keys=True, default=str).encode()).hexdigest()


def _firecrawl_api_key(explicit_key: str | None = None) -> str | None:
    """Resolve the server-side key without printing or exporting it.

    Vercel loads the configured environment variable itself. The local
    scheduled Python job also supports the existing ignored `web/.env.local`
    file so it shares the dashboard's already-configured key.
    """
    if explicit_key:
        return explicit_key
    if key := os.getenv("FIRECRAWL_API_KEY"):
        return key
    env_path = PROJECT_ROOT / "web" / ".env.local"
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            match = re.match(r"^\s*FIRECRAWL_API_KEY\s*=\s*(.*?)\s*$", line)
            if match:
                return match.group(1).strip().strip('"').strip("'") or None
    except OSError:
        pass
    return None


def capture_iapd_live_page(
    *, individual_crd: str, database_url: str, url: str | None = None,
    api_key: str | None = None, session: requests.Session | None = None,
) -> dict[str, Any]:
    """Capture one public IAPD individual page with Firecrawl and reconcile it."""
    api_key = _firecrawl_api_key(api_key)
    if not api_key:
        raise IAPDLiveUnavailable("FIRECRAWL_API_KEY is not configured")
    url = url or build_iapd_individual_url(individual_crd)
    client = session or requests.Session()
    response = client.post(
        FIRECRAWL_URL,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={"url": url, "formats": ["markdown", "html"], "onlyMainContent": True, "maxAge": 0},
        timeout=45,
    )
    if response.status_code in {401, 403, 429}:
        raise IAPDLiveUnavailable(f"Firecrawl unavailable for IAPD capture: HTTP {response.status_code}")
    response.raise_for_status()
    payload = response.json()
    data = payload.get("data", payload)
    markdown = data.get("markdown") or ""
    if not markdown.strip():
        raise IAPDLiveUnavailable("Firecrawl returned no readable IAPD page content")
    metadata = data.get("metadata") or {}
    normalized = normalize_iapd_live_markdown(markdown, expected_crd=individual_crd)
    capture_id = _stable_id("firecrawl", individual_crd, _hash({"url": url, "markdown": markdown}))
    now = datetime.now(timezone.utc)
    raw_payload = {"payload": payload, "markdown": markdown[:500_000]}
    with __import__("psycopg").connect(database_url) as connection:
        with connection.transaction():
            connection.execute(
                """INSERT INTO iapd_live_captures (capture_id,individual_crd,source_url,source_title,retrieved_at,retrieval_status,content_hash,parser_version,raw_payload,created_at)
                   VALUES (%s,%s,%s,%s,%s,'SUCCESS',%s,%s,%s,%s)
                   ON CONFLICT (capture_id) DO NOTHING""",
                (capture_id, individual_crd, url, metadata.get("title"), now, _hash(raw_payload), PARSER_VERSION, json.dumps(raw_payload), now),
            )
            fields = normalized["fields"]
            enrichment_id = _stable_id(capture_id, "enrichment")
            connection.execute(
                """INSERT INTO iapd_individual_live_enrichments (enrichment_id,capture_id,individual_crd,full_name,current_employer_name,current_employer_crd,business_address,phone,website,registration_status,registration_date,branch_locations,disclosure_summary,normalized_fields,confidence,freshness,retrieved_at,created_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'live_confirmed',%s,%s)
                   ON CONFLICT (enrichment_id) DO NOTHING""",
                (enrichment_id, capture_id, individual_crd, fields["full_name"], fields["current_employer_name"], fields["current_employer_crd"], fields["business_address"], fields["phone"], fields["website"], fields["registration_status"], fields["registration_date"], json.dumps(fields["branch_locations"]), fields["disclosure_summary"], json.dumps(fields), normalized["confidence"], now, now),
            )
        reconciliation = reconcile_iapd_individual(individual_crd=individual_crd, database_url=database_url, live_capture_id=capture_id)
    return {"status": "success", "capture_id": capture_id, "individual_crd": individual_crd, "confidence": normalized["confidence"], "reconciliation": reconciliation}


def reconcile_iapd_individual(*, individual_crd: str, database_url: str, live_capture_id: str | None = None) -> dict[str, Any]:
    """Create an auditable effective record; never overwrite either source."""
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        monthly = connection.execute(
            """SELECT s.snapshot_id,s.snapshot_date,e.employer_firm_crd,e.employer_name,e.address_line_1,e.address_line_2,e.city,e.state,e.postal_code,e.country,
                      (SELECT r.status FROM iapd_individual_current_registrations r WHERE r.snapshot_id=s.snapshot_id AND r.individual_crd=e.individual_crd ORDER BY r.status_date DESC NULLS LAST LIMIT 1) registration_status,
                      (SELECT r.status_date FROM iapd_individual_current_registrations r WHERE r.snapshot_id=s.snapshot_id AND r.individual_crd=e.individual_crd ORDER BY r.status_date DESC NULLS LAST LIMIT 1) registration_date
                 FROM iapd_individual_snapshots s JOIN iapd_individual_current_employments e ON e.snapshot_id=s.snapshot_id
                WHERE s.status='SUCCESS' AND e.individual_crd=%s ORDER BY s.snapshot_date DESC LIMIT 1""", (individual_crd,)
        ).fetchone()
        live_sql = "SELECT * FROM iapd_individual_live_enrichments WHERE individual_crd=%s"
        params: list[Any] = [individual_crd]
        if live_capture_id:
            live_sql += " AND capture_id=%s"; params.append(live_capture_id)
        live_sql += " ORDER BY retrieved_at DESC LIMIT 1"
        live = connection.execute(live_sql, params).fetchone()
        address = None
        if monthly:
            address = ", ".join(str(value) for value in [monthly["address_line_1"], monthly["address_line_2"], monthly["city"], monthly["state"], monthly["postal_code"], monthly["country"]] if value)
        conflicts: dict[str, dict[str, Any]] = {}
        if monthly and live:
            for field, monthly_value, live_value in (("current_employer_crd", monthly["employer_firm_crd"], live["current_employer_crd"]), ("current_employer_name", monthly["employer_name"], live["current_employer_name"])):
                if monthly_value and live_value and str(monthly_value).casefold() != str(live_value).casefold():
                    conflicts[field] = {"monthly": monthly_value, "live": live_value}
        effective = {
            "current_employer_crd": monthly["employer_firm_crd"] if monthly and monthly["employer_firm_crd"] else (live or {}).get("current_employer_crd"),
            "current_employer_name": monthly["employer_name"] if monthly and monthly["employer_name"] else (live or {}).get("current_employer_name"),
            "registration_status": monthly["registration_status"] if monthly and monthly["registration_status"] else (live or {}).get("registration_status"),
            "registration_date": monthly["registration_date"] if monthly and monthly["registration_date"] else (live or {}).get("registration_date"),
            "business_address": (live or {}).get("business_address") or address,
            "phone": (live or {}).get("phone"), "website": (live or {}).get("website"),
            "branch_locations": (live or {}).get("branch_locations") or [],
            "disclosure_summary": (live or {}).get("disclosure_summary"),
        }
        freshness = "conflict" if conflicts else "monthly_confirmed" if monthly else "live_confirmed" if live else "missing"
        if freshness != "conflict" and not monthly and live and live["confidence"] == "LOW": freshness = "partial"
        now = datetime.now(timezone.utc)
        reconciliation_id = _stable_id(individual_crd, monthly["snapshot_id"] if monthly else None, live["capture_id"] if live else None)
        connection.execute(
            """INSERT INTO iapd_individual_reconciliations (reconciliation_id,individual_crd,snapshot_id,capture_id,effective_fields,freshness,confidence,conflicts,created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (reconciliation_id) DO NOTHING""",
            (reconciliation_id, individual_crd, monthly["snapshot_id"] if monthly else None, live["capture_id"] if live else None, json.dumps(effective), freshness, live["confidence"] if live else ("HIGH" if monthly else "LOW"), json.dumps(conflicts), now),
        )
    return {"individual_crd": individual_crd, "freshness": freshness, "conflicts": conflicts, "effective_fields": effective}


def rebuild_iapd_reconciliations(*, database_url: str, limit: int | None = None) -> dict[str, Any]:
    """Rebuild derived effective records without deleting source snapshots."""
    import psycopg
    with psycopg.connect(database_url) as connection:
        statement = "SELECT DISTINCT individual_crd FROM iapd_individuals ORDER BY individual_crd"
        if limit is not None:
            statement += " LIMIT %s"
            rows = connection.execute(statement, (limit,)).fetchall()
        else:
            rows = connection.execute(statement).fetchall()
    results = [reconcile_iapd_individual(individual_crd=str(row[0]), database_url=database_url) for row in rows]
    return {"status": "success", "reconciled": len(results), "freshness_counts": {value: sum(item["freshness"] == value for item in results) for value in {item["freshness"] for item in results}}}


def main() -> None:
    parser = argparse.ArgumentParser(description="Live IAPD representative fallback")
    parser.add_argument("command", choices=("crawl", "reconcile"))
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--crd", required=True)
    parser.add_argument("--url")
    args = parser.parse_args()
    result = capture_iapd_live_page(individual_crd=args.crd, database_url=args.database_url, url=args.url) if args.command == "crawl" else reconcile_iapd_individual(individual_crd=args.crd, database_url=args.database_url)
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()

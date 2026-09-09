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
import time
from urllib.parse import urlparse
from datetime import datetime, timezone
from typing import Any

import requests

from src.iapd import _clean, _stable_id
from src.config import PROJECT_ROOT
from src.iapd_reconciliation import reconcile_values, VERSION


PARSER_VERSION = "iapd-live-v2"
FIRECRAWL_URL = "https://api.firecrawl.dev/v2/scrape"
IAPD_INDIVIDUAL_URL = "https://adviserinfo.sec.gov/individual/summary/{crd}"


class IAPDLiveUnavailable(RuntimeError):
    """A live IAPD fallback cannot be retrieved or safely interpreted."""


def build_iapd_individual_url(individual_crd: str) -> str:
    if not re.fullmatch(r"[0-9]+", individual_crd.strip()):
        raise ValueError("Individual CRD must contain digits only")
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
    crd = _labelled(markdown, "Individual CRD", "CRD Number", "CRD", "CRD#")
    if crd:
        digits = re.search(r"\d+", crd)
        crd = digits.group(0) if digits else None
    if expected_crd and crd and crd != expected_crd:
        raise IAPDLiveUnavailable(f"Live IAPD page CRD {crd} does not match requested CRD {expected_crd}")
    if not crd:
        raise IAPDLiveUnavailable("Live page does not explicitly identify an individual CRD")
    full_name = _labelled(markdown, "Representative Name", "Individual Name", "Name")
    if not full_name:
        identity = re.search(r"(?m)^([A-Z][A-Z .,'’\-]+)\s*\n\s*\nCRD#:\s*" + re.escape(crd) + r"\b", markdown)
        full_name = _clean(identity.group(1)) if identity else None
    phone = _labelled(markdown, "Phone Number", "Phone", "Business Phone")
    website = _labelled(markdown, "Website", "Web Address")
    if website:
        website = _first_url(website)
    address = _labelled(markdown, "Business Address", "Office Address", "Address")
    disclosures = _labelled(markdown, "Disclosure", "Disciplinary History", "Disclosure Summary")
    status = _labelled(markdown, "Registration Status", "Status")
    registration_date = _labelled(markdown, "Registration Date", "Status Date")
    employer_name = _labelled(markdown, "Current Employer", "Current Firm", "Employer")
    employer_crd = _labelled(markdown, "Current Employer CRD", "Firm CRD", "Organization CRD")
    current_section = re.split(r"Current Registration\(s\)", markdown, maxsplit=1)
    current_employers = []
    if len(current_section) == 2:
        current_text = current_section[1].split("Previous Registration(s)")[0]
        for name, firm_crd, link_crd in re.findall(r"\[([^\n\]]+?)\s*\(CRD#:\s*(\d+)\)\]\(https://adviserinfo\.sec\.gov/firm/summary/(\d+)\)", current_text):
            item = {"name":name.strip(), "crd":firm_crd}
            if firm_crd == link_crd and item not in current_employers:
                current_employers.append(item)
        if len(current_employers) == 1:
            employer_name = employer_name or current_employers[0]['name']
            employer_crd = employer_crd or current_employers[0]['crd']
            status = status or 'CURRENT_REGISTRATION_REPORTED'
            office = re.search(r"\]\(https://adviserinfo\.sec\.gov/firm/summary/\d+\)\s*\n\s*\n([^\n]+)\s*\n\s*\nRegistered with this firm since ([0-9/]+)", current_text)
            if office:
                address = address or _clean(office.group(1))
                registration_date = registration_date or office.group(2)
    if disclosures is None:
        disclosure_count = re.search(r"(?m)^\s*(\d+)\s*\n\s*\nDisclosures\s*$", markdown)
        if disclosure_count:
            disclosures = f"{disclosure_count.group(1)} disclosures reported"
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
        "current_employers": current_employers,
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
    reconcile: bool = True,
) -> dict[str, Any]:
    """Capture one public IAPD individual page with Firecrawl and reconcile it."""
    api_key = _firecrawl_api_key(api_key)
    if not api_key:
        raise IAPDLiveUnavailable("FIRECRAWL_API_KEY is not configured")
    canonical_url = build_iapd_individual_url(individual_crd)
    url = url or canonical_url
    parsed_url = urlparse(url)
    if (parsed_url.scheme != "https" or parsed_url.netloc != "adviserinfo.sec.gov"
            or parsed_url.path.rstrip('/') != urlparse(canonical_url).path or parsed_url.query or parsed_url.fragment):
        raise ValueError("Only the matching official IAPD individual summary URL is supported")
    client = session or requests.Session()
    for attempt in range(3):
        try:
            response = client.post(
                FIRECRAWL_URL,
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"url": url, "formats": ["markdown"], "onlyMainContent": True, "maxAge": 0},
                timeout=45,
            )
            if response.status_code != 429 and response.status_code < 500:
                break
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 2:
                raise IAPDLiveUnavailable("Live retrieval timed out or could not connect") from None
        if attempt < 2:
            time.sleep(2 ** attempt)
    if response.status_code in {401, 403, 429}:
        raise IAPDLiveUnavailable(f"Firecrawl unavailable for IAPD capture: HTTP {response.status_code}")
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("success") is False:
        raise IAPDLiveUnavailable("Firecrawl returned an unsuccessful or malformed response")
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        raise IAPDLiveUnavailable("Firecrawl returned malformed page data")
    markdown = data.get("markdown") or ""
    if not isinstance(markdown, str) or len(markdown) > 500_000:
        raise IAPDLiveUnavailable("IAPD page exceeds the bounded content limit or is malformed")
    if not markdown.strip():
        raise IAPDLiveUnavailable("Firecrawl returned no readable IAPD page content")
    metadata = data.get("metadata") or {}
    if not isinstance(metadata, dict) or metadata.get("statusCode", 200) in (403, 404, 429, 503):
        raise IAPDLiveUnavailable("IAPD source page was blocked or unavailable")
    normalized = normalize_iapd_live_markdown(markdown, expected_crd=individual_crd)
    now = datetime.now(timezone.utc)
    capture_id = _stable_id("firecrawl", PARSER_VERSION, individual_crd, now.isoformat(), _hash({"url": url, "markdown": markdown}))
    raw_payload = {"markdown": markdown, "metadata": {"title": metadata.get("title"), "sourceURL": url}}
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
        reconciliation = reconcile_iapd_individual(individual_crd=individual_crd, database_url=database_url, live_capture_id=capture_id) if reconcile else None
    return {"status": "success", "capture_id": capture_id, "individual_crd": individual_crd, "confidence": normalized["confidence"], "fields": fields, "reconciliation": reconciliation}


def reconcile_iapd_individual(*, individual_crd: str, database_url: str,
                              live_capture_id: str | None = None,
                              monthly_rows_override: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Create an auditable effective record; never overwrite either source."""
    import psycopg
    from psycopg.rows import dict_row

    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        monthly_rows = monthly_rows_override if monthly_rows_override is not None else connection.execute(
            """SELECT s.snapshot_id,s.snapshot_date,s.source_url,i.full_name,e.employer_firm_crd,e.employer_name,e.address_line_1,e.address_line_2,e.city,e.state,e.postal_code,e.country,
                      (SELECT r.status FROM iapd_individual_current_registrations r WHERE r.snapshot_id=s.snapshot_id AND r.employment_id=e.employment_id ORDER BY r.status_date DESC NULLS LAST,r.registration_id LIMIT 1) registration_status,
                      (SELECT r.status_date FROM iapd_individual_current_registrations r WHERE r.snapshot_id=s.snapshot_id AND r.employment_id=e.employment_id ORDER BY r.status_date DESC NULLS LAST,r.registration_id LIMIT 1) registration_date,
                      (SELECT CASE WHEN bool_or(coalesce(d.reg_action,false) or coalesce(d.criminal,false) or coalesce(d.bankrupt,false) or coalesce(d.civil_judgment,false) or coalesce(d.bond,false) or coalesce(d.judgment,false) or coalesce(d.investigation,false) or coalesce(d.customer_complaint,false) or coalesce(d.termination,false)) THEN 'disclosure flag reported' ELSE '0 disclosures reported' END FROM iapd_individual_disclosure_flags d WHERE d.snapshot_id=s.snapshot_id AND d.individual_crd=e.individual_crd) disclosure_summary
                 FROM iapd_individual_snapshots s JOIN iapd_individual_current_employments e ON e.snapshot_id=s.snapshot_id
                 JOIN iapd_individuals i ON i.individual_crd=e.individual_crd
                WHERE s.snapshot_id=(select snapshot_id from iapd_individual_snapshots where status='SUCCESS' order by snapshot_date desc limit 1)
                AND e.individual_crd=%s ORDER BY e.employer_firm_crd,e.employment_id""", (individual_crd,)
        ).fetchall()
        monthly = monthly_rows[0] if monthly_rows else None
        live_sql = """SELECT e.*,c.source_url FROM iapd_individual_live_enrichments e
                      JOIN iapd_live_captures c ON c.capture_id=e.capture_id WHERE e.individual_crd=%s"""
        params: list[Any] = [individual_crd]
        if live_capture_id:
            live_sql += " AND e.capture_id=%s"; params.append(live_capture_id)
        live_sql += " ORDER BY e.retrieved_at DESC LIMIT 1"
        live = connection.execute(live_sql, params).fetchone()
        effective, freshness, conflicts = reconcile_values(monthly_rows, live)
        now = datetime.now(timezone.utc)
        reconciliation_id = _stable_id(VERSION, individual_crd, monthly["snapshot_id"] if monthly else None, live["capture_id"] if live else None, _hash(effective))
        connection.execute(
            """INSERT INTO iapd_individual_reconciliations (reconciliation_id,individual_crd,snapshot_id,capture_id,effective_fields,freshness,confidence,conflicts,created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (reconciliation_id) DO NOTHING""",
            (reconciliation_id, individual_crd, monthly["snapshot_id"] if monthly else None, live["capture_id"] if live else None, json.dumps(effective), freshness, live["confidence"] if live else ("HIGH" if monthly else "LOW"), json.dumps(conflicts), now),
        )
    return {"individual_crd": individual_crd, "snapshot_id": monthly["snapshot_id"] if monthly else None,
            "capture_id": live["capture_id"] if live else None,
            "freshness": freshness, "conflicts": conflicts, "effective_fields": effective}


def rebuild_iapd_reconciliations(*, database_url: str, limit: int | None = None) -> dict[str, Any]:
    """Rebuild derived effective records without deleting source snapshots."""
    import psycopg
    with psycopg.connect(database_url) as connection:
        statement = "SELECT individual_crd FROM iapd_individuals UNION SELECT individual_crd FROM iapd_individual_live_enrichments ORDER BY individual_crd"
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

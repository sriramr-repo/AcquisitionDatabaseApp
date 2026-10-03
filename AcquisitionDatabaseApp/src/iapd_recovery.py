"""Bounded operator recovery; monthly failures never erase the prior snapshot."""
import argparse
import json
import os
import re
import shutil
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import requests

from src.config import settings
from src.iapd import (
    IAPD_BROWSER_URL, IAPDFeedUnavailable, _sha256, _stable_id,
    build_iapd_feed_url, download_iapd_feed, parse_iapd_zip,
    repair_iapd_firm_summaries, run_iapd_monthly,
)
from src.iapd_live import FIRECRAWL_URL, _firecrawl_api_key, capture_iapd_live_page


def compilation_dates(links):
    dates = set()
    for link in links:
        parsed = urlparse(link)
        if parsed.scheme != 'https' or parsed.netloc != 'reports.adviserinfo.sec.gov':
            continue
        match = re.fullmatch(r'/reports/CompilationReports/IA_INDVL_Feed_(\d{2})_(\d{2})_(\d{4})\.xml\.zip', parsed.path)
        if match:
            month, day, year = map(int, match.groups())
            try:
                value = date(year, month, day)
                if value <= date.today():
                    dates.add(value)
            except ValueError:
                pass
    return sorted(dates, reverse=True)


def discover_compilation(session=None):
    key = _firecrawl_api_key()
    if not key:
        raise RuntimeError('FIRECRAWL_API_KEY is not configured')
    response = (session or requests.Session()).post(FIRECRAWL_URL,
        headers={'Authorization': f'Bearer {key}'},
        json={'url': IAPD_BROWSER_URL, 'formats': ['links'], 'maxAge': 0}, timeout=45)
    response.raise_for_status()
    payload = response.json()
    data = payload.get('data') if isinstance(payload, dict) else None
    if not isinstance(data, dict) or not isinstance(data.get('links'), list):
        raise RuntimeError('Compilation discovery returned no usable links')
    return compilation_dates([x for x in data['links'] if isinstance(x, str)])


def inspect_feed_health(zip_path: Path, *, previous_count: int | None = None,
                        minimum_records: int = 100_000) -> dict[str, int | float]:
    """Fully parse a candidate before any active publication is changed."""
    counts: Counter[str] = Counter()
    seen: set[str] = set()
    issues: list[dict] = []
    for person in parse_iapd_zip(zip_path, issues=issues):
        counts["records"] += 1
        crd = str(person["individual_crd"])
        if crd in seen:
            counts["duplicate_records"] += 1
        else:
            seen.add(crd)
        counts["current_employments"] += len(person.get("current_employments") or [])
        counts["current_registrations"] += sum(len(row.get("registrations") or []) for row in person.get("current_employments") or [])
        counts["disclosure_rows"] += len(person.get("disclosures") or [])
    counts["unique_representatives"] = len(seen)
    counts["parse_issues"] = len(issues)
    records = counts["records"]
    if records < minimum_records:
        raise IAPDFeedUnavailable(f"Candidate feed is implausibly small: {records} records")
    duplicate_ratio = counts["duplicate_records"] / records if records else 1.0
    if duplicate_ratio > 0.05:
        raise IAPDFeedUnavailable(f"Candidate feed duplicate ratio is too high: {duplicate_ratio:.3f}")
    if counts["current_employments"] < records // 2:
        raise IAPDFeedUnavailable("Candidate feed is structurally incomplete: too few current employments")
    if previous_count and not 0.60 <= len(seen) / previous_count <= 1.60:
        raise IAPDFeedUnavailable(
            f"Candidate representative count changed implausibly: prior={previous_count}, current={len(seen)}"
        )
    return {**dict(counts), "duplicate_ratio": duplicate_ratio}


def _previous_local_count() -> int | None:
    try:
        current = json.loads((settings.BASE_DIR / "iapd" / "local" / "current.json").read_text())
        manifest = json.loads((Path(current["dataset_path"]) / "build-manifest.json").read_text())
        return int(manifest["person_count"])
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _quarantine(path: Path, reason: str) -> Path:
    root = settings.BASE_DIR / "iapd" / "quarantine"
    root.mkdir(parents=True, exist_ok=True)
    destination = root / f"{path.name}.{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}.quarantine"
    os.replace(path, destination)
    (destination.with_suffix(destination.suffix + ".json")).write_text(json.dumps({
        "source_file": path.name, "reason": reason, "quarantined_at": datetime.now(timezone.utc).isoformat()
    }, sort_keys=True))
    return destination


def _record_feed_run(database_url: str, report: dict) -> None:
    import psycopg
    with psycopg.connect(database_url) as connection:
        connection.execute(
            """INSERT INTO iapd_feed_runs
               (run_id,requested_date,selected_date,status,source_url,source_hash,attempts,result_counts,started_at,completed_at,created_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (run_id) DO UPDATE SET selected_date=EXCLUDED.selected_date,status=EXCLUDED.status,
                 source_url=EXCLUDED.source_url,source_hash=EXCLUDED.source_hash,
                 attempts=EXCLUDED.attempts,result_counts=EXCLUDED.result_counts,completed_at=EXCLUDED.completed_at""",
            (report["run_id"], report["requested_date"], report.get("snapshot_date"), report["status"],
             report.get("source_url"), report.get("source_hash"), json.dumps(report.get("attempts", [])),
             json.dumps(report.get("counts", {})), report["started_at"], report.get("completed_at"), report["started_at"]),
        )


def monthly_refresh_with_recovery(*, database_url: str, run_date: date | None = None,
                                  force: bool = False, session=None,
                                  minimum_records: int = 100_000) -> dict:
    """Try the scheduled URL, then the newest validated official discovered feed."""
    requested = run_date or date.today()
    if requested.day != 4 and not force:
        return {"status":"no_new_feed","reason":"not_scheduled_day","snapshot_date":requested.isoformat()}
    started = datetime.now(timezone.utc)
    report = {"run_id":_stable_id("iapd-feed-run",started.isoformat()),
              "requested_date":requested.isoformat(),"started_at":started,"attempts":[],"counts":{},"status":"running"}
    _record_feed_run(database_url, report)
    candidates = [requested]
    selected_fallback = False
    for candidate in candidates:
        url = build_iapd_feed_url(candidate)
        try:
            zip_path, source_url, source_hash = download_iapd_feed(candidate, session=session)
            report["attempts"].append({"url":url,"status":"retrieved"})
            _record_feed_run(database_url, report)
            try:
                health = inspect_feed_health(zip_path, previous_count=_previous_local_count(), minimum_records=minimum_records)
            except IAPDFeedUnavailable as error:
                quarantine = _quarantine(zip_path, str(error))
                report["attempts"][-1].update({"status":"quarantined","reason":str(error),"path":str(quarantine)})
                raise
            summary = repair_iapd_firm_summaries(
                snapshot_date=candidate, source_url=source_url, source_zip=zip_path,
                database_url=database_url,
            )
            report.update(summary)
            report.update({"status":"fallback_success" if selected_fallback else "success",
                           "snapshot_date":candidate.isoformat(),"source_zip":str(zip_path.resolve()),
                           "source_url":source_url,"source_hash":source_hash,"counts":health})
            break
        except (IAPDFeedUnavailable, requests.RequestException) as error:
            match = re.search(r"HTTP\s+(\d{3})", str(error), re.IGNORECASE)
            reason = f"HTTP_{match.group(1)}" if match else type(error).__name__.upper()
            if not report["attempts"] or report["attempts"][-1].get("url") != url:
                report["attempts"].append({"url":url,"status":"failed","reason":reason})
            elif report["attempts"][-1]["status"] == "retrieved":
                report["attempts"][-1].update({"status":"failed","reason":reason})
            _record_feed_run(database_url, report)
            if len(candidates) == 1:
                try:
                    discovered = discover_compilation(session=session)
                except (requests.RequestException, RuntimeError, ValueError):
                    discovered = []
                candidates.extend(value for value in discovered if value != requested)
                selected_fallback = bool(discovered)
            continue
    else:
        report.update({"status":"failed_preserved_previous","reason":"no_valid_official_feed"})
    report["completed_at"] = datetime.now(timezone.utc)
    _record_feed_run(database_url, report)
    return report


def record_failure(database_url, crd, error):
    import psycopg
    now = datetime.now(timezone.utc)
    # Do not persist exception strings that might contain credentials or request headers.
    details = {'error_type': type(error).__name__, 'parser_version': 'iapd-recovery-v1'}
    with psycopg.connect(database_url, connect_timeout=15) as conn:
        conn.execute('''INSERT INTO iapd_import_issues
          (issue_id,individual_crd,stage,severity,issue_code,message,details,created_at)
          VALUES (%s,%s,'live_recovery','warning','LIVE_UNAVAILABLE',%s,%s,%s)''',
          (_stable_id(crd,now.isoformat()),crd,'Live retrieval unavailable; prior evidence retained',json.dumps(details),now))


def recover(*, database_url, crds=(), monthly=True, limit=10):
    if not 1 <= limit <= 100:
        raise ValueError('limit must be between 1 and 100')
    people = list(dict.fromkeys(str(crd).strip() for crd in crds))
    if len(people) > limit or any(not re.fullmatch(r'[0-9]+', crd) for crd in people):
        raise ValueError('Provide valid CRDs within the explicit batch limit')
    report = {'monthly': None, 'live': []}
    if monthly:
        report['monthly'] = run_iapd_monthly(database_url=database_url,force=True)
        if report['monthly'].get('status') == 'fallback_required':
            try:
                candidates = discover_compilation()
                if candidates:
                    report['monthly'] = run_iapd_monthly(database_url=database_url,run_date=candidates[0],force=True)
            except (requests.RequestException, RuntimeError, ValueError) as error:
                record_failure(database_url,None,error)
    for crd in people:
        try:
            report['live'].append(capture_iapd_live_page(individual_crd=crd,database_url=database_url))
        except (requests.RequestException, RuntimeError, ValueError) as error:
            record_failure(database_url,crd,error)
            report['live'].append({'individual_crd':crd,'status':'unavailable','error_type':type(error).__name__})
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database-url',required=True)
    parser.add_argument('--crd',action='append',default=[])
    parser.add_argument('--limit',type=int,default=10)
    parser.add_argument('--live-only',action='store_true')
    parser.add_argument('--latest-feed',action='store_true',help='Discover and validate the newest official compilation feed')
    parser.add_argument('--date',type=date.fromisoformat)
    args = parser.parse_args()
    if args.latest_feed:
        result = monthly_refresh_with_recovery(database_url=args.database_url,run_date=args.date,force=True)
    else:
        result = recover(database_url=args.database_url,crds=args.crd,limit=args.limit,monthly=not args.live_only)
    print(json.dumps(result,default=str,indent=2))


if __name__ == '__main__':
    main()

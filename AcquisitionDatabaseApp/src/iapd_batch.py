"""Restartable, bounded live-IAPD enrichment batches for official individual pages."""
from __future__ import annotations

import argparse
import json
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

import duckdb

from src.iapd import _stable_id
from src.iapd_live import (
    PARSER_VERSION,
    IAPDLiveUnavailable,
    build_iapd_individual_url,
    capture_iapd_live_page, reconcile_iapd_individual,
)
from src.iapd_reconciliation import VERSION


TRANSIENT_MARKERS = ("429", "rate", "timeout", "connect", "500", "502", "503", "504")


def _safe_reason(error: Exception) -> str:
    text = str(error).lower()
    if "crd" in text and "match" in text:
        return "CRD_MISMATCH"
    if any(marker in text for marker in TRANSIENT_MARKERS):
        return "TRANSIENT_SOURCE_FAILURE"
    if isinstance(error, ValueError):
        return "INVALID_REQUEST"
    return "SOURCE_UNAVAILABLE"


def _safe_error_detail(error: Exception) -> str:
    """Keep an actionable bounded message without persisting credentials or headers."""
    detail = re.sub(r"(?i)(bearer|api[_ -]?key)\s+\S+", r"\1 [redacted]", str(error))
    return detail[:500]


def _select_candidates_for_enqueue(
    candidates: list[tuple[str, int]],
    existing: dict[str, tuple[str, datetime | None, int, dict[str, Any]]],
    *,
    fresh_after: datetime,
    enqueue_limit: int,
    max_attempts: int,
) -> tuple[list[tuple[str, int]], int]:
    """Choose a bounded deterministic slice without filling Neon with the universe."""
    selected: list[tuple[str, int]] = []
    fresh_skipped = 0
    for crd, order in candidates:
        prior = existing.get(crd)
        if (
            prior
            and prior[0] in {"SUCCESS", "UNCHANGED", "SKIPPED_FRESH"}
            and prior[1]
            and prior[1] >= fresh_after
            and (prior[3] or {}).get("reconciliation_version") == VERSION
        ):
            fresh_skipped += 1
            continue
        if prior and prior[0] == "FAILED" and prior[2] >= max_attempts:
            continue
        selected.append((crd, order))
        if len(selected) >= enqueue_limit:
            break
    return selected, fresh_skipped


def _candidate_representatives(
    *, database_url: str, local_database: Path, include_national: bool = False,
    selected_crds: Iterable[str] = (),
) -> list[tuple[str, int]]:
    """Return unique CRDs in deterministic business-priority order."""
    import psycopg
    selected = {str(value).strip() for value in selected_crds}
    if any(not re.fullmatch(r"[0-9]+", value) for value in selected):
        raise ValueError("Representative CRDs must contain digits only")
    with psycopg.connect(database_url) as connection:
        rows = connection.execute(
            """SELECT f.firm_id,coalesce(s.priority_category,'PRIORITY_Z'),x.total_aum
                 FROM firms f LEFT JOIN firm_scores s USING(firm_id,dataset_version)
                 LEFT JOIN firm_facts x USING(firm_id,dataset_version)
                WHERE f.dataset_version=(SELECT dataset_version FROM dataset_versions ORDER BY published_at DESC,dataset_version DESC LIMIT 1)"""
        ).fetchall()
    firms = {str(row[0]): (str(row[1]), row[2]) for row in rows}
    priority_rank = {"PRIORITY_A": 0, "PRIORITY_B": 1, "PRIORITY_C": 2}
    best: dict[str, tuple[Any, ...]] = {}
    with duckdb.connect(str(local_database), read_only=True) as connection:
        links = connection.execute(
            "SELECT firm_id,individual_crd FROM iapd_current_links ORDER BY firm_id,individual_crd"
        ).fetchall()
        for firm_id, individual_crd in links:
            crd = str(individual_crd)
            if selected and crd not in selected:
                continue
            firm = firms.get(str(firm_id))
            if firm is None and not include_national:
                continue
            category, aum = firm or ("PRIORITY_Z", None)
            under_200m = 0 if aum is not None and float(aum) < 200_000_000 else 1
            rank = (under_200m, priority_rank.get(category, 9), str(firm_id), int(crd))
            if crd not in best or rank < best[crd]:
                best[crd] = rank
        if include_national and not selected:
            for (individual_crd,) in connection.execute("SELECT individual_crd FROM iapd_people ORDER BY individual_crd").fetchall():
                crd = str(individual_crd)
                best.setdefault(crd, (2, 9, "", int(crd)))
    return [(crd, index) for index, (crd, _) in enumerate(sorted(best.items(), key=lambda item: item[1]), 1)]


def enqueue_live_jobs(
    *, database_url: str, local_database: Path, batch_id: str,
    include_national: bool = False, selected_crds: Iterable[str] = (),
    max_attempts: int = 3, enqueue_limit: int = 25, freshness_days: int = 30,
) -> dict[str, int]:
    import psycopg
    if not 1 <= max_attempts <= 10:
        raise ValueError("max_attempts must be between 1 and 10")
    candidates = _candidate_representatives(
        database_url=database_url, local_database=local_database,
        include_national=include_national, selected_crds=selected_crds,
    )
    if not 1 <= enqueue_limit <= 1_000:
        raise ValueError("enqueue_limit must be between 1 and 1000")
    now = datetime.now(timezone.utc)
    fresh_after = now - timedelta(days=freshness_days)
    with psycopg.connect(database_url) as connection:
        existing = {str(row[0]): (str(row[1]), row[2], int(row[3]), row[4] or {}) for row in connection.execute(
            "SELECT individual_crd,status,last_success_at,attempt_count,result_summary FROM iapd_live_jobs WHERE parser_version=%s",
            (PARSER_VERSION,),
        ).fetchall()}
    selected, fresh_skipped = _select_candidates_for_enqueue(
        candidates, existing, fresh_after=fresh_after,
        enqueue_limit=enqueue_limit, max_attempts=max_attempts,
    )
    rows = [(
        _stable_id(PARSER_VERSION, crd), batch_id, crd,
        build_iapd_individual_url(crd), PARSER_VERSION, order, max_attempts, now, now,
    ) for crd, order in selected]
    with psycopg.connect(database_url) as connection:
        with connection.cursor() as cursor:
            cursor.executemany(
                """INSERT INTO iapd_live_jobs
                   (job_id,batch_id,individual_crd,source_url,parser_version,priority_order,status,max_attempts,created_at,updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,'QUEUED',%s,%s,%s)
                   ON CONFLICT (individual_crd,parser_version) DO UPDATE SET
                     batch_id=EXCLUDED.batch_id,priority_order=EXCLUDED.priority_order,
                     max_attempts=EXCLUDED.max_attempts,
                     status='QUEUED',
                     updated_at=EXCLUDED.updated_at""", rows,
            )
    return {"candidates": len(candidates), "queued": len(rows), "fresh_skipped": fresh_skipped}


def _review_items(result: dict[str, Any]) -> list[tuple[str, dict[str, Any]]]:
    reconciliation = result.get("reconciliation") or {}
    effective = reconciliation.get("effective_fields") or {}
    conflicts = reconciliation.get("conflicts") or {}
    items = [(key.upper(), value) for key, value in conflicts.items()]
    if len(effective.get("current_employers") or []) > 1:
        items.append(("MULTIPLE_CURRENT_EMPLOYERS", {"current_employers": effective["current_employers"]}))
    return items


def _sync_review_queue(connection, *, individual_crd: str, capture_id: str,
                       reconciliation: dict[str, Any], observed_at: datetime) -> list[tuple[str, dict[str, Any]]]:
    result = {"reconciliation": reconciliation}
    review_items = _review_items(result)
    active_reasons = {reason for reason, _ in review_items}
    open_reviews = connection.execute(
        "SELECT review_id,reason_code FROM iapd_manual_review_queue WHERE individual_crd=%s AND status='OPEN'",
        (individual_crd,),
    ).fetchall()
    for review in open_reviews:
        if review["reason_code"] not in active_reasons:
            connection.execute(
                "UPDATE iapd_manual_review_queue SET status='RESOLVED',updated_at=%s WHERE review_id=%s",
                (observed_at, review["review_id"]),
            )
    for reason, details in review_items:
        review_id = _stable_id(individual_crd, capture_id, reason)
        connection.execute(
            """INSERT INTO iapd_manual_review_queue
               (review_id,individual_crd,reason_code,status,monthly_snapshot_id,live_capture_id,details,created_at,updated_at)
               VALUES (%s,%s,%s,'OPEN',%s,%s,%s,%s,%s) ON CONFLICT (review_id) DO NOTHING""",
            (review_id, individual_crd, reason, reconciliation.get("snapshot_id"),
             capture_id, json.dumps(details), observed_at, observed_at),
        )
    return review_items


def _monthly_rows_from_local(local_database: Path, individual_crd: str) -> list[dict[str, Any]]:
    with duckdb.connect(str(local_database), read_only=True) as connection:
        snapshot = connection.execute(
            "SELECT snapshot_id,CAST(snapshot_date AS VARCHAR),source_url FROM iapd_snapshot LIMIT 1"
        ).fetchone()
        rows = connection.execute(
            """SELECT p.full_name,p.payload_json,l.employment_json
                 FROM iapd_people p JOIN iapd_current_links l USING(snapshot_id,individual_crd)
                WHERE p.individual_crd=? ORDER BY l.firm_id,l.employment_id""", (individual_crd,),
        ).fetchall()
    if not snapshot:
        return []
    result = []
    for full_name, payload_json, employment_json in rows:
        payload = json.loads(payload_json) if isinstance(payload_json, str) else payload_json
        employment = json.loads(employment_json) if isinstance(employment_json, str) else employment_json
        registrations = employment.get("registrations") or []
        statuses = {row.get("status") for row in registrations if row.get("status")}
        dates = sorted(str(row["status_date"]) for row in registrations if row.get("status_date"))
        disclosure_rows = payload.get("disclosures") or []
        has_disclosure = any(any(value is True for value in row.values()) for row in disclosure_rows)
        result.append({
            "snapshot_id": snapshot[0], "snapshot_date": snapshot[1], "source_url": snapshot[2],
            "full_name": full_name, "employer_firm_crd": employment.get("employer_firm_crd"),
            "employer_name": employment.get("employer_name"),
            **{key: employment.get(key) for key in ("address_line_1","address_line_2","city","state","postal_code","country")},
            "registration_status": next(iter(statuses)) if len(statuses) == 1 else None,
            "registration_date": dates[-1] if dates else None,
            "disclosure_summary": "disclosure flag reported" if has_disclosure else "0 disclosures reported",
        })
    return result


def _process_job(database_url: str, local_database: Path, job: dict[str, Any], *, freshness_days: int) -> str:
    import psycopg
    from psycopg.rows import dict_row
    now = datetime.now(timezone.utc)
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        previous = connection.execute(
            """SELECT capture_id,content_hash,retrieved_at FROM iapd_live_captures
                WHERE individual_crd=%s AND retrieval_status='SUCCESS'
                ORDER BY retrieved_at DESC LIMIT 1""", (job["individual_crd"],),
        ).fetchone()
        if previous and previous["retrieved_at"] >= now - timedelta(days=freshness_days):
            reconciliation = reconcile_iapd_individual(
                individual_crd=job["individual_crd"], database_url=database_url,
                live_capture_id=previous["capture_id"],
                monthly_rows_override=_monthly_rows_from_local(local_database, job["individual_crd"]),
            )
            review_items = _sync_review_queue(
                connection, individual_crd=job["individual_crd"],
                capture_id=previous["capture_id"], reconciliation=reconciliation,
                observed_at=now,
            )
            connection.execute(
                """UPDATE iapd_live_jobs SET status='SKIPPED_FRESH',last_success_at=%s,
                   last_content_hash=%s,failure_reason=NULL,result_summary=%s,updated_at=%s WHERE job_id=%s""",
                (previous["retrieved_at"], previous["content_hash"],
                 json.dumps({"capture_id": previous["capture_id"], "freshness": reconciliation["freshness"],
                             "reconciliation_version": VERSION}),
                 now, job["job_id"]),
            )
            return "conflicted" if review_items else "skipped"
        connection.execute(
            """UPDATE iapd_live_jobs SET status='RUNNING',attempt_count=attempt_count+1,
               last_attempt_at=%s,next_attempt_at=NULL,failure_reason=NULL,updated_at=%s WHERE job_id=%s""",
            (now, now, job["job_id"]),
        )
    try:
        result = capture_iapd_live_page(
            individual_crd=job["individual_crd"], database_url=database_url,
            reconcile=False,
        )
        capture_id = result["capture_id"]
        result["reconciliation"] = reconcile_iapd_individual(
            individual_crd=job["individual_crd"], database_url=database_url,
            live_capture_id=capture_id,
            monthly_rows_override=_monthly_rows_from_local(local_database, job["individual_crd"]),
        )
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            capture = connection.execute(
                "SELECT content_hash FROM iapd_live_captures WHERE capture_id=%s", (capture_id,),
            ).fetchone()
            unchanged = bool(previous and capture and previous["content_hash"] == capture["content_hash"])
            status = "UNCHANGED" if unchanged else "SUCCESS"
            completed = datetime.now(timezone.utc)
            connection.execute(
                """UPDATE iapd_live_jobs SET status=%s,last_success_at=%s,last_content_hash=%s,
                   result_summary=%s,updated_at=%s WHERE job_id=%s""",
                (status, completed, capture["content_hash"] if capture else None,
                 json.dumps({"capture_id": capture_id, "freshness": result["reconciliation"]["freshness"],
                             "reconciliation_version": VERSION}),
                 completed, job["job_id"]),
            )
            review_items = _sync_review_queue(
                connection, individual_crd=job["individual_crd"], capture_id=capture_id,
                reconciliation=result["reconciliation"], observed_at=completed,
            )
        return "unchanged" if unchanged else ("conflicted" if review_items else "succeeded")
    except Exception as error:
        reason = _safe_reason(error)
        transient = reason == "TRANSIENT_SOURCE_FAILURE"
        with psycopg.connect(database_url, row_factory=dict_row) as connection:
            current = connection.execute(
                "SELECT attempt_count,max_attempts FROM iapd_live_jobs WHERE job_id=%s", (job["job_id"],),
            ).fetchone()
            retry = transient and current and current["attempt_count"] < current["max_attempts"]
            next_attempt = datetime.now(timezone.utc) + timedelta(seconds=min(3600, 30 * 2 ** max(0, int(current["attempt_count"]) - 1))) if retry else None
            connection.execute(
                """UPDATE iapd_live_jobs SET status=%s,next_attempt_at=%s,failure_reason=%s,
                   result_summary=%s,updated_at=now() WHERE job_id=%s""",
                ("RETRY_PENDING" if retry else "FAILED", next_attempt, reason,
                 json.dumps({"error_type": type(error).__name__, "detail": _safe_error_detail(error)}),
                 job["job_id"]),
            )
            if reason == "CRD_MISMATCH":
                review_id = _stable_id(job["individual_crd"], reason, job["attempt_count"])
                connection.execute(
                    """INSERT INTO iapd_manual_review_queue
                       (review_id,individual_crd,reason_code,status,details,created_at,updated_at)
                       VALUES (%s,%s,%s,'OPEN',%s,now(),now()) ON CONFLICT (review_id) DO NOTHING""",
                    (review_id, job["individual_crd"], reason, json.dumps({"source_url": job["source_url"]})),
                )
        return "retry_pending" if retry else "failed"


def run_live_batch(
    *, database_url: str, local_database: Path, limit: int = 25, workers: int = 2,
    freshness_days: int = 30, include_national: bool = False,
    selected_crds: Iterable[str] = (), resume: bool = False, max_attempts: int = 3,
) -> dict[str, Any]:
    """Run one checkpointed batch. Large universes require repeated bounded runs."""
    import psycopg
    from psycopg.rows import dict_row
    if not 1 <= limit <= 1_000:
        raise ValueError("limit must be between 1 and 1000")
    if not 1 <= workers <= 8:
        raise ValueError("workers must be between 1 and 8")
    if not 1 <= freshness_days <= 365:
        raise ValueError("freshness_days must be between 1 and 365")
    started = datetime.now(timezone.utc)
    scope = "national" if include_national else "firm_universe"
    batch_id = _stable_id("iapd-live-batch", scope, started.isoformat())
    with psycopg.connect(database_url) as connection:
        connection.execute(
            """INSERT INTO iapd_live_batches
               (batch_id,status,scope,options,counts,started_at,created_at,updated_at)
               VALUES (%s,'RUNNING',%s,%s,'{}'::jsonb,%s,%s,%s)""",
            (batch_id, scope, json.dumps({"limit":limit,"workers":workers,"freshness_days":freshness_days,"resume":resume}), started, started, started),
        )
    if not resume:
        enqueue_live_jobs(
            database_url=database_url, local_database=local_database, batch_id=batch_id,
            include_national=include_national, selected_crds=selected_crds,
            max_attempts=max_attempts, enqueue_limit=limit,
            freshness_days=freshness_days,
        )
    else:
        with psycopg.connect(database_url) as connection:
            connection.execute(
                """UPDATE iapd_live_jobs SET status='QUEUED',attempt_count=0,next_attempt_at=NULL,
                   failure_reason=NULL,updated_at=now()
                   WHERE parser_version=%s AND (status='FAILED' OR
                     (status='RUNNING' AND updated_at < now()-interval '10 minutes'))""", (PARSER_VERSION,),
            )
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        jobs = connection.execute(
            """SELECT * FROM iapd_live_jobs
                WHERE status IN ('QUEUED','RETRY_PENDING','FAILED')
                  AND parser_version=%s
                  AND attempt_count < max_attempts
                  AND (next_attempt_at IS NULL OR next_attempt_at<=now())
                  AND (%s OR batch_id=%s)
                ORDER BY priority_order,individual_crd LIMIT %s""",
            (PARSER_VERSION, resume, batch_id, limit),
        ).fetchall()
    counts: Counter[str] = Counter()
    checkpoint = None
    with ThreadPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_process_job, database_url, local_database, dict(job), freshness_days=freshness_days): job for job in jobs}
        for future in as_completed(futures):
            job = futures[future]
            try:
                counts[future.result()] += 1
            except Exception:
                counts["failed"] += 1
            checkpoint = str(job["individual_crd"])
    completed = datetime.now(timezone.utc)
    status = "PARTIAL" if counts.get("failed") or counts.get("retry_pending") else "SUCCESS"
    with psycopg.connect(database_url) as connection:
        connection.execute(
            """UPDATE iapd_live_batches SET status=%s,counts=%s,checkpoint_crd=%s,
               completed_at=%s,updated_at=%s WHERE batch_id=%s""",
            (status, json.dumps(dict(counts)), checkpoint, completed, completed, batch_id),
        )
    return {"batch_id": batch_id, "scope": scope, "status": status.lower(), "attempted": len(jobs), **dict(counts)}


def quality_report(*, database_url: str) -> dict[str, Any]:
    import psycopg
    with psycopg.connect(database_url) as connection:
        latest = connection.execute("SELECT snapshot_date,status,individual_count,source_url FROM iapd_individual_snapshots ORDER BY snapshot_date DESC LIMIT 1").fetchone()
        jobs = dict(connection.execute("SELECT status,count(*) FROM iapd_live_jobs GROUP BY status").fetchall())
        freshness = dict(connection.execute("WITH latest AS (SELECT DISTINCT ON (individual_crd) individual_crd,freshness FROM iapd_individual_reconciliations ORDER BY individual_crd,created_at DESC) SELECT freshness,count(*) FROM latest GROUP BY freshness").fetchall())
        reviews = dict(connection.execute("SELECT reason_code,count(*) FROM iapd_manual_review_queue WHERE status='OPEN' GROUP BY reason_code").fetchall())
        issues = dict(connection.execute("SELECT issue_code,count(*) FROM iapd_import_issues GROUP BY issue_code").fetchall())
    return {"latest_snapshot": latest, "live_jobs": jobs, "freshness": freshness, "open_reviews": reviews, "import_issues": issues}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("run", "resume", "quality"))
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--local-database", type=Path)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--workers", type=int, default=2)
    parser.add_argument("--freshness-days", type=int, default=30)
    parser.add_argument("--all", action="store_true", dest="include_national")
    parser.add_argument("--crd", action="append", default=[])
    args = parser.parse_args()
    if args.command == "quality":
        result = quality_report(database_url=args.database_url)
    else:
        if not args.local_database:
            parser.error("--local-database is required for run/resume")
        result = run_live_batch(
            database_url=args.database_url, local_database=args.local_database,
            limit=args.limit, workers=args.workers, freshness_days=args.freshness_days,
            include_national=args.include_national, selected_crds=args.crd,
            resume=args.command == "resume",
        )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()

"""Audited, source-specific IAPD conflict decisions; source records stay immutable."""
from __future__ import annotations

import argparse
import copy
import json
import os
from datetime import datetime, timezone

from src.iapd import _stable_id

RESOLUTIONS = {"monthly_preferred", "live_preferred", "resolved_same_entity"}


def resolved_fields(record, review, *, resolution, reviewer, rationale, evidence_url):
    if resolution not in RESOLUTIONS or not all(str(v or "").strip() for v in (reviewer, rationale, evidence_url)):
        raise ValueError("A valid resolution, reviewer, rationale and evidence URL are required")
    expected_url = f'https://adviserinfo.sec.gov/individual/summary/{review["individual_crd"]}'
    if evidence_url != expected_url:
        raise ValueError("Evidence must identify the matching official individual page")
    effective = copy.deepcopy(record["effective_fields"])
    conflicts = copy.deepcopy(record["conflicts"])
    key = review["reason_code"].lower()
    conflict = conflicts.get(key)
    if key != "multiple_current_employers" and conflict is None:
        raise ValueError("The reviewed conflict is absent from the current reconciliation")
    if key == "multiple_current_employers" and resolution != "monthly_preferred":
        raise ValueError("Multiple employers must be preserved; this operation supports monthly_preferred only")
    if conflict and resolution == "live_preferred":
        if conflict.get("live") is None or isinstance(conflict["live"], (list, dict)):
            raise ValueError("A scalar source value is required for live preference")
        effective[key] = conflict["live"]
        effective.setdefault("provenance", {})[key] = {
            "source_type": "live_page", "source_id": record["capture_id"],
            "observed_at": conflict.get("live_observed_at"),
        }
    if conflict:
        del conflicts[key]
    decision = {"resolution": resolution, "reviewer": reviewer, "rationale": rationale,
                "evidence_url": evidence_url, "review_id": review["review_id"],
                "reviewed_at": datetime.now(timezone.utc).isoformat(),
                "original_details": review["details"]}
    effective.setdefault("review_decisions", []).append(decision)
    freshness = "conflict" if conflicts else "partial" if effective.get("stale") else "monthly_confirmed" if record.get("snapshot_id") else "live_confirmed"
    return effective, conflicts, freshness, decision


def resolve_review(*, database_url, review_id, resolution, reviewer, rationale, evidence_url):
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        if not connection.execute("SELECT pg_try_advisory_xact_lock(73492108) AS locked").fetchone()["locked"]:
            raise RuntimeError("IAPD worker active; retry review after the batch")
        review = connection.execute("SELECT * FROM iapd_manual_review_queue WHERE review_id=%s FOR UPDATE", (review_id,)).fetchone()
        if not review:
            raise ValueError("Unknown review ID")
        if review["status"] != "OPEN":
            return {"status": "already_reviewed", "review_id": review_id}
        record = connection.execute("SELECT * FROM iapd_individual_reconciliations WHERE individual_crd=%s ORDER BY created_at DESC,reconciliation_id DESC LIMIT 1 FOR UPDATE", (review["individual_crd"],)).fetchone()
        if not record or record["snapshot_id"] != review["monthly_snapshot_id"] or record["capture_id"] != review["live_capture_id"]:
            raise ValueError("Source versions changed; review current evidence before resolving")
        effective, conflicts, freshness, decision = resolved_fields(record, review, resolution=resolution, reviewer=reviewer, rationale=rationale, evidence_url=evidence_url)
        new_id = _stable_id("iapd-review-v1", record["reconciliation_id"], review_id, resolution)
        connection.execute("""INSERT INTO iapd_individual_reconciliations
            (reconciliation_id,individual_crd,snapshot_id,capture_id,effective_fields,freshness,confidence,conflicts,created_at)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,now())""",
            (new_id,review["individual_crd"],record["snapshot_id"],record["capture_id"],json.dumps(effective),freshness,record["confidence"],json.dumps(conflicts)))
        connection.execute("UPDATE iapd_manual_review_queue SET status='RESOLVED',details=%s,updated_at=now() WHERE review_id=%s",
            (json.dumps({**review["details"], "review_decision": decision}),review_id))
        # Firm conflict indicators are computed from latest reconciliation/open reviews.
        # Both become visible atomically at this transaction's commit.
    return {"status": "resolved", "review_id": review_id, "individual_crd": review["individual_crd"], "resolution": resolution, "reconciliation_id": new_id}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--review-id", required=True)
    parser.add_argument("--resolution", choices=sorted(RESOLUTIONS), required=True)
    parser.add_argument("--reviewer", required=True)
    parser.add_argument("--rationale", required=True)
    parser.add_argument("--evidence-url", required=True)
    args = parser.parse_args()
    print(json.dumps(resolve_review(database_url=os.environ["PUBLISHER_DATABASE_URL"], **vars(args)), indent=2))


if __name__ == "__main__":
    main()

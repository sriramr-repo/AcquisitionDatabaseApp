"""Publish compact IAPD snapshot-change summaries to the dashboard database."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


CHANGE_COLUMNS = {
    "new_representatives": "new_representative_count",
    "disappeared_representatives": "representative_no_longer_present_count",
    "employer_changes": "employer_change_count",
    "registration_changes": "registration_change_count",
    "disclosure_changes": "disclosure_change_count",
    "material_contact_changes": "material_contact_change_count",
}
HASH = re.compile(r"^[a-f0-9]{64}$")


class IAPDChangePublishError(RuntimeError):
    """Raised when a compact comparison cannot be published safely."""


def validate_change_report(report: dict[str, Any]) -> dict[str, Any]:
    """Validate the local comparison contract before any database write."""
    if report.get("status") not in {"success", "baseline"}:
        raise IAPDChangePublishError("comparison status must be success or baseline")
    comparison_id = str(report.get("comparison_id") or "")
    if not HASH.fullmatch(comparison_id):
        raise IAPDChangePublishError("comparison_id must be a SHA-256 identifier")
    current = report.get("current")
    previous = report.get("previous")
    if not isinstance(current, dict) or not current.get("snapshot_id"):
        raise IAPDChangePublishError("current snapshot metadata is required")
    if not current.get("dataset_version") or not current.get("snapshot_date"):
        raise IAPDChangePublishError("current dataset version and date are required")
    if report["status"] == "baseline" and previous is not None:
        raise IAPDChangePublishError("baseline comparison cannot include a previous snapshot")
    if report["status"] == "success" and not isinstance(previous, dict):
        raise IAPDChangePublishError("successful comparison requires a previous snapshot")
    counts = report.get("counts")
    if not isinstance(counts, dict) or set(counts) != set(CHANGE_COLUMNS):
        raise IAPDChangePublishError("comparison counts do not match the canonical change types")
    if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in counts.values()):
        raise IAPDChangePublishError("comparison counts must be non-negative integers")
    guardrails = report.get("interpretation_guardrails")
    if not isinstance(guardrails, list) or not guardrails:
        raise IAPDChangePublishError("interpretation guardrails are required")
    combined_guardrails = " ".join(str(value).lower() for value in guardrails)
    for phrase in ("does not establish termination", "does not establish misconduct", "seller intent"):
        if phrase not in combined_guardrails:
            raise IAPDChangePublishError(f"missing interpretation guardrail: {phrase}")
    firm_changes = report.get("firm_changes")
    if not isinstance(firm_changes, list):
        raise IAPDChangePublishError("firm_changes must be a list")
    seen: set[str] = set()
    for row in firm_changes:
        firm_id = str(row.get("firm_id") or "") if isinstance(row, dict) else ""
        row_counts = row.get("counts") if isinstance(row, dict) else None
        samples = row.get("representative_samples") if isinstance(row, dict) else None
        if not firm_id or firm_id in seen:
            raise IAPDChangePublishError("firm changes contain a missing or duplicate firm_id")
        seen.add(firm_id)
        if not isinstance(row_counts, dict) or set(row_counts) != set(CHANGE_COLUMNS):
            raise IAPDChangePublishError(f"invalid counts for firm {firm_id}")
        if any(not isinstance(value, int) or isinstance(value, bool) or value < 0 for value in row_counts.values()):
            raise IAPDChangePublishError(f"invalid count value for firm {firm_id}")
        if not isinstance(samples, dict) or any(
            key not in CHANGE_COLUMNS or not isinstance(value, list)
            for key, value in samples.items()
        ):
            raise IAPDChangePublishError(f"invalid representative samples for firm {firm_id}")
    if report["status"] == "baseline" and (firm_changes or any(counts.values())):
        raise IAPDChangePublishError("baseline comparison must contain zero changes")
    if int(report.get("affected_firm_count", -1)) != len(firm_changes):
        raise IAPDChangePublishError("affected_firm_count does not match firm_changes")
    return report


def publish_change_report(
    *, report_path: Path, database_url: str, dry_run: bool = False,
) -> dict[str, Any]:
    """Upsert one deterministic comparison and dashboard-firm summaries."""
    import psycopg

    report_path = Path(report_path).resolve()
    report = validate_change_report(json.loads(report_path.read_text()))
    current = report["current"]
    previous = report.get("previous") or {}
    dataset_version = str(current["dataset_version"])
    comparison_id = str(report["comparison_id"])
    now = datetime.now(timezone.utc)
    rows = []
    for item in report["firm_changes"]:
        counts = item["counts"]
        rows.append((
            comparison_id, str(item["firm_id"]), dataset_version,
            *(int(counts[name]) for name in CHANGE_COLUMNS),
            json.dumps(item["representative_samples"], sort_keys=True),
        ))
    if dry_run:
        return {
            "status": "validated", "comparison_id": comparison_id,
            "dataset_version": dataset_version,
            "national_affected_firms": len(report["firm_changes"]),
            "publish_candidates": len(rows), "counts": report["counts"],
        }
    with psycopg.connect(database_url) as connection:
        with connection.transaction():
            active = connection.execute(
                """SELECT dataset_version FROM dataset_versions
                   ORDER BY published_at DESC,dataset_version DESC LIMIT 1"""
            ).fetchone()
            if not active or str(active[0]) != dataset_version:
                raise IAPDChangePublishError(
                    "comparison dataset must match the active dashboard dataset"
                )
            connection.execute(
                """INSERT INTO iapd_snapshot_comparisons
                   (comparison_id,dataset_version,current_snapshot_id,previous_snapshot_id,
                    current_snapshot_date,previous_snapshot_date,status,counts,
                    national_affected_firm_count,published_firm_count,artifact_name,
                    interpretation_guardrails,published_at,created_at,updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,0,%s,%s,%s,%s,%s)
                   ON CONFLICT (comparison_id) DO UPDATE SET
                    status=EXCLUDED.status,counts=EXCLUDED.counts,
                    national_affected_firm_count=EXCLUDED.national_affected_firm_count,
                    artifact_name=EXCLUDED.artifact_name,
                    interpretation_guardrails=EXCLUDED.interpretation_guardrails,
                    published_at=EXCLUDED.published_at,updated_at=EXCLUDED.updated_at""",
                (
                    comparison_id, dataset_version, current["snapshot_id"],
                    previous.get("snapshot_id"), current["snapshot_date"],
                    previous.get("snapshot_date"), report["status"],
                    json.dumps(report["counts"], sort_keys=True),
                    len(report["firm_changes"]), report_path.name,
                    json.dumps(report["interpretation_guardrails"]), now, now, now,
                ),
            )
            connection.execute(
                """CREATE TEMP TABLE iapd_change_publish (
                    comparison_id text,firm_id text,dataset_version text,
                    new_representative_count integer,
                    representative_no_longer_present_count integer,
                    employer_change_count integer,registration_change_count integer,
                    disclosure_change_count integer,material_contact_change_count integer,
                    representative_samples jsonb
                ) ON COMMIT DROP"""
            )
            if rows:
                with connection.cursor().copy(
                    "COPY iapd_change_publish FROM STDIN"
                ) as copy:
                    for row in rows:
                        copy.write_row(row)
            connection.execute(
                """DELETE FROM iapd_firm_change_summaries s
                   WHERE s.comparison_id=%s
                     AND NOT EXISTS (
                       SELECT 1 FROM iapd_change_publish p
                       WHERE p.comparison_id=s.comparison_id AND p.firm_id=s.firm_id
                     )""",
                (comparison_id,),
            )
            published = connection.execute(
                """INSERT INTO iapd_firm_change_summaries
                   (comparison_id,firm_id,dataset_version,new_representative_count,
                    representative_no_longer_present_count,employer_change_count,
                    registration_change_count,disclosure_change_count,
                    material_contact_change_count,representative_samples,created_at,updated_at)
                   SELECT p.comparison_id,p.firm_id,p.dataset_version,
                    p.new_representative_count,p.representative_no_longer_present_count,
                    p.employer_change_count,p.registration_change_count,
                    p.disclosure_change_count,p.material_contact_change_count,
                    p.representative_samples,%s,%s
                   FROM iapd_change_publish p JOIN firms f
                     ON f.firm_id=p.firm_id AND f.dataset_version=p.dataset_version
                   ON CONFLICT (comparison_id,firm_id) DO UPDATE SET
                    new_representative_count=EXCLUDED.new_representative_count,
                    representative_no_longer_present_count=EXCLUDED.representative_no_longer_present_count,
                    employer_change_count=EXCLUDED.employer_change_count,
                    registration_change_count=EXCLUDED.registration_change_count,
                    disclosure_change_count=EXCLUDED.disclosure_change_count,
                    material_contact_change_count=EXCLUDED.material_contact_change_count,
                    representative_samples=EXCLUDED.representative_samples,
                    updated_at=EXCLUDED.updated_at RETURNING firm_id""",
                (now, now),
            ).fetchall()
            published_count = len(published)
            connection.execute(
                """UPDATE iapd_snapshot_comparisons
                   SET published_firm_count=%s,updated_at=%s WHERE comparison_id=%s""",
                (published_count, now, comparison_id),
            )
    return {
        "status": "success", "comparison_id": comparison_id,
        "dataset_version": dataset_version,
        "national_affected_firms": len(report["firm_changes"]),
        "published_dashboard_firms": published_count,
        "counts": report["counts"],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("publish",))
    parser.add_argument("--report-path", type=Path, required=True)
    parser.add_argument("--database-url")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not args.dry_run and not args.database_url:
        parser.error("--database-url is required unless --dry-run is used")
    print(json.dumps(publish_change_report(
        report_path=args.report_path, database_url=args.database_url or "",
        dry_run=args.dry_run,
    ), indent=2, default=str))


if __name__ == "__main__":
    main()

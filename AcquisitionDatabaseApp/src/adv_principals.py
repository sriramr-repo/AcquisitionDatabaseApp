"""Structured Form ADV Schedule A/B principal ingestion and IAPD coverage."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, TextIO


COVERAGE_STATUSES = frozenset(
    {
        "CURRENT_IAPD_REPRESENTATIVE",
        "SCHEDULE_A_PRINCIPAL",
        "SCHEDULE_B_OWNER",
        "ENTITY_OWNER_ONLY",
        "CCO_OR_SIGNATORY_ONLY",
        "NO_PUBLIC_INDIVIDUAL_PROFILE",
        "RECONCILIATION_REQUIRED",
        "SOURCE_NOT_PROCESSED",
        "SOURCE_RETRIEVAL_FAILED",
    }
)


ALIASES = {
    "firm_id": (
        "organizationcrd", "organizationcrdnumber", "firmcrd", "firmcrdnumber",
        "advisercrd", "advisercrdnumber", "orgcrd", "orgpk", "crdnumber", "crd",
    ),
    "filing_date": (
        "filingdate", "datesubmitted", "submissiondate", "dtrelsd", "releasedate",
        "latestadvfilingdate", "filingdt",
    ),
    "schedule_type": ("scheduletype", "schedule", "schedtype"),
    "full_legal_name": (
        "fulllegalname", "dvfulllegalname", "ivfulllegalname", "ownername",
        "principalname", "legalname", "name",
    ),
    "principal_type": (
        "defei", "dvdef", "ivdef", "entitytype", "ownertype", "persontype",
    ),
    "title_status": (
        "titleorstatus", "titlestatus", "dvtitle", "ivtitle", "dvstatus",
        "ivstatus", "title", "status",
    ),
    "date_acquired": (
        "datetitleorstatusacquired", "dvdatestatusacquired",
        "ivdatestatusacquired", "dateacquired", "acquireddate",
    ),
    "ownership_code": (
        "ownershipcode", "dvownershipcode", "ivownershipcode", "ownership",
    ),
    "control_person": (
        "controlperson", "dvcontrolperson", "ivcontrolperson",
        "controlpersonflag", "control",
    ),
    "public_reporting_company": (
        "pr", "dvpr", "ivpr", "publicreportingcompany", "publicreportingflag",
    ),
    "related_crd": (
        "crdnoifnone", "dvcrdnum", "ivcrdnum", "relatedcrd", "individualcrd",
        "ownercrd", "principalcrd", "personcrd", "crdno",
    ),
}


def _normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(value).casefold())


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    result = " ".join(str(value).replace("\u00a0", " ").split())
    if not result or result.casefold() in {"n/a", "na", "none", "null", "unknown", "-", "--"}:
        return None
    return result


def _bool(value: Any) -> bool | None:
    cleaned = _clean(value)
    if cleaned is None:
        return None
    normalized = cleaned.casefold()
    if normalized in {"y", "yes", "true", "t", "1"}:
        return True
    if normalized in {"n", "no", "false", "f", "0"}:
        return False
    return None


def _date_value(value: Any) -> str | None:
    """Normalize common SEC date encodings so latest-filing ordering is stable."""
    cleaned = _clean(value)
    if cleaned is None:
        return None
    for pattern in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%Y%m%d"):
        try:
            return datetime.strptime(cleaned, pattern).date().isoformat()
        except ValueError:
            continue
    return cleaned


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _column_map(fieldnames: Iterable[str]) -> dict[str, str]:
    available = {_normalized(field): field for field in fieldnames if field}
    result: dict[str, str] = {}
    for canonical, aliases in ALIASES.items():
        for alias in aliases:
            if alias in available:
                result[canonical] = available[alias]
                break
    return result


def _schedule_type(source_name: str, row: dict[str, Any], columns: dict[str, str]) -> str | None:
    explicit = _clean(row.get(columns.get("schedule_type", "")))
    if explicit:
        normalized = explicit.upper().replace("SCHEDULE", "").strip(" _-")
        if normalized in {"A", "B"}:
            return normalized
    source = _normalized(source_name)
    if "schedulea" in source or "directowner" in source or "executiveofficer" in source:
        return "A"
    if "scheduleb" in source or "indirectowner" in source:
        return "B"
    return None


def _principal_type(value: Any) -> str:
    normalized = (_clean(value) or "").upper().replace(" ", "_")
    if normalized in {"I", "INDIVIDUAL", "PERSON", "NATURAL_PERSON"}:
        return "INDIVIDUAL"
    if normalized in {"FE", "FOREIGN_ENTITY"}:
        return "FOREIGN_ENTITY"
    if normalized in {"DE", "DOMESTIC_ENTITY", "ENTITY", "ORGANIZATION"}:
        return "DOMESTIC_ENTITY"
    return "UNKNOWN"


def _principal_id(record: dict[str, Any], content_hash: str, source_name: str) -> str:
    values = (
        record.get("firm_id"), record.get("filing_date"), record.get("schedule_type"),
        record.get("full_legal_name"), record.get("title_status"),
        record.get("ownership_code"), record.get("related_crd"), source_name, content_hash,
    )
    return hashlib.sha256("|".join("" if item is None else str(item) for item in values).encode()).hexdigest()


def parse_adv_principal_csv(
    stream: TextIO, *, source_name: str, content_hash: str
) -> Iterator[dict[str, Any]]:
    """Yield normalized Schedule A/B rows from one official CSV table."""
    reader = csv.DictReader(stream)
    columns = _column_map(reader.fieldnames or [])
    if "firm_id" not in columns or "full_legal_name" not in columns:
        return
    for row in reader:
        schedule_type = _schedule_type(source_name, row, columns)
        if schedule_type not in {"A", "B"}:
            continue
        firm_id = _clean(row.get(columns["firm_id"]))
        name = _clean(row.get(columns["full_legal_name"]))
        if not firm_id or not name:
            continue
        firm_digits = re.search(r"\d+", firm_id.replace(",", ""))
        firm_id = firm_digits.group(0) if firm_digits else firm_id
        related_crd = _clean(row.get(columns.get("related_crd", "")))
        if related_crd:
            crd_digits = re.search(r"\d+", related_crd.replace(",", ""))
            related_crd = crd_digits.group(0) if crd_digits else None
        record = {
            "firm_id": firm_id,
            "filing_date": _date_value(row.get(columns.get("filing_date", ""))),
            "schedule_type": schedule_type,
            "principal_type": _principal_type(row.get(columns.get("principal_type", ""))),
            "full_legal_name": name,
            "title_status": _clean(row.get(columns.get("title_status", ""))),
            "date_acquired": _clean(row.get(columns.get("date_acquired", ""))),
            "ownership_code": _clean(row.get(columns.get("ownership_code", ""))),
            "control_person": _bool(row.get(columns.get("control_person", ""))),
            "public_reporting_company": _bool(
                row.get(columns.get("public_reporting_company", ""))
            ),
            "related_crd": related_crd,
            "source_file_name": source_name,
            "content_hash": content_hash,
        }
        record["principal_id"] = _principal_id(record, content_hash, source_name)
        yield record


def iter_adv_principals(path: Path | str) -> Iterator[dict[str, Any]]:
    """Stream principal rows from a CSV or a multi-table Form ADV ZIP."""
    path = Path(path)
    content_hash = _file_sha256(path)
    if zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as archive:
            for member in archive.infolist():
                if member.is_dir() or not member.filename.casefold().endswith(".csv"):
                    continue
                with archive.open(member) as raw:
                    text = io.TextIOWrapper(raw, encoding="utf-8-sig", errors="replace", newline="")
                    yield from parse_adv_principal_csv(
                        text, source_name=member.filename, content_hash=content_hash
                    )
    else:
        with path.open(encoding="utf-8-sig", errors="replace", newline="") as stream:
            yield from parse_adv_principal_csv(
                stream, source_name=path.name, content_hash=content_hash
            )


def import_adv_principals(
    path: Path | str, *, database_url: str, source_url: str | None = None
) -> dict[str, Any]:
    """Upsert official principal facts for current dashboard firms only."""
    import psycopg

    now = datetime.now(timezone.utc)
    parsed = 0
    published = 0
    published_firms: set[str] = set()
    with psycopg.connect(database_url) as connection:
        current_firms = {
            str(row[0]) for row in connection.execute(
                """SELECT firm_id FROM firms WHERE dataset_version=(
                       SELECT dataset_version FROM dataset_versions ORDER BY published_at DESC LIMIT 1
                   )"""
            ).fetchall()
        }
        rows: list[tuple[Any, ...]] = []

        def flush() -> None:
            if not rows:
                return
            with connection.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO iapd_firm_principals
                       (principal_id,firm_id,filing_date,schedule_type,principal_type,
                        full_legal_name,title_status,date_acquired,ownership_code,
                        control_person,public_reporting_company,related_crd,source_url,
                        source_file_name,content_hash,published_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (principal_id) DO UPDATE SET
                         filing_date=EXCLUDED.filing_date,
                         principal_type=EXCLUDED.principal_type,
                         full_legal_name=EXCLUDED.full_legal_name,
                         title_status=EXCLUDED.title_status,
                         date_acquired=EXCLUDED.date_acquired,
                         ownership_code=EXCLUDED.ownership_code,
                         control_person=EXCLUDED.control_person,
                         public_reporting_company=EXCLUDED.public_reporting_company,
                         related_crd=EXCLUDED.related_crd,
                         source_url=EXCLUDED.source_url,
                         content_hash=EXCLUDED.content_hash,
                         published_at=EXCLUDED.published_at""",
                    rows,
                )
            rows.clear()

        with connection.transaction():
            for record in iter_adv_principals(path):
                parsed += 1
                if record["firm_id"] not in current_firms:
                    continue
                rows.append(
                    (
                        record["principal_id"], record["firm_id"], record["filing_date"],
                        record["schedule_type"], record["principal_type"],
                        record["full_legal_name"], record["title_status"],
                        record["date_acquired"], record["ownership_code"],
                        record["control_person"], record["public_reporting_company"],
                        record["related_crd"], source_url, record["source_file_name"],
                        record["content_hash"], now,
                    )
                )
                published += 1
                published_firms.add(record["firm_id"])
                if len(rows) >= 2_000:
                    flush()
            flush()
    coverage = refresh_iapd_firm_coverage(database_url=database_url)
    return {
        "status": "success",
        "parsed": parsed,
        "published": published,
        "firms": len(published_firms),
        "coverage": coverage,
    }


def classify_coverage(
    *, summary_present: bool, representative_count: int | None,
    reported_state_iar_count: int | None, schedule_a_individuals: int = 0,
    schedule_b_individuals: int = 0, entity_principals: int = 0,
    cco_or_signatory_count: int = 0, source_retrieval_failed: bool = False,
) -> str:
    if source_retrieval_failed:
        return "SOURCE_RETRIEVAL_FAILED"
    if not summary_present:
        return "SOURCE_NOT_PROCESSED"
    if (representative_count or 0) > 0:
        return "CURRENT_IAPD_REPRESENTATIVE"
    if (reported_state_iar_count or 0) > 0:
        return "RECONCILIATION_REQUIRED"
    if schedule_a_individuals > 0:
        return "SCHEDULE_A_PRINCIPAL"
    if schedule_b_individuals > 0:
        return "SCHEDULE_B_OWNER"
    if entity_principals > 0:
        return "ENTITY_OWNER_ONLY"
    if cco_or_signatory_count > 0:
        return "CCO_OR_SIGNATORY_ONLY"
    return "NO_PUBLIC_INDIVIDUAL_PROFILE"


def refresh_iapd_firm_coverage(*, database_url: str) -> dict[str, Any]:
    """Materialize one explainable personnel-coverage result for every current firm."""
    import psycopg
    from psycopg.rows import dict_row

    now = datetime.now(timezone.utc)
    with psycopg.connect(database_url, row_factory=dict_row) as connection:
        dataset = connection.execute(
            "SELECT dataset_version FROM dataset_versions ORDER BY published_at DESC LIMIT 1"
        ).fetchone()
        if not dataset:
            raise ValueError("No dashboard dataset is available")
        dataset_version = str(dataset["dataset_version"])
        rows = connection.execute(
            """WITH latest_snapshot AS (
                   SELECT snapshot_id FROM iapd_firm_summaries
                   ORDER BY snapshot_date DESC,published_at DESC LIMIT 1
               ), latest_principal_filing AS (
                   SELECT firm_id,max(filing_date) filing_date FROM iapd_firm_principals
                   GROUP BY firm_id
               ), principal_counts AS (
                   SELECT p.firm_id,
                     count(*) filter(where p.schedule_type='A' and p.principal_type='INDIVIDUAL') schedule_a_individuals,
                     count(*) filter(where p.schedule_type='B' and p.principal_type='INDIVIDUAL') schedule_b_individuals,
                     count(*) filter(where p.principal_type in ('DOMESTIC_ENTITY','FOREIGN_ENTITY','UNKNOWN')) entity_principals
                   FROM iapd_firm_principals p JOIN latest_principal_filing l
                     ON l.firm_id=p.firm_id AND l.filing_date IS NOT DISTINCT FROM p.filing_date
                   GROUP BY p.firm_id
               )
               SELECT f.firm_id,ff.state_iar_count,s.snapshot_id,s.representative_count,
                      (s.firm_id is not null) summary_present,
                      coalesce(p.schedule_a_individuals,0) schedule_a_individuals,
                      coalesce(p.schedule_b_individuals,0) schedule_b_individuals,
                      coalesce(p.entity_principals,0) entity_principals
                 FROM firms f LEFT JOIN firm_facts ff USING(firm_id,dataset_version)
                 LEFT JOIN iapd_firm_summaries s ON s.firm_id=f.firm_id
                   AND s.snapshot_id=(SELECT snapshot_id FROM latest_snapshot)
                 LEFT JOIN principal_counts p ON p.firm_id=f.firm_id
                WHERE f.dataset_version=%s ORDER BY f.firm_id""",
            (dataset_version,),
        ).fetchall()
        output = []
        counts: dict[str, int] = {}
        for row in rows:
            status = classify_coverage(
                summary_present=bool(row["summary_present"]),
                representative_count=row["representative_count"],
                reported_state_iar_count=row["state_iar_count"],
                schedule_a_individuals=int(row["schedule_a_individuals"]),
                schedule_b_individuals=int(row["schedule_b_individuals"]),
                entity_principals=int(row["entity_principals"]),
            )
            counts[status] = counts.get(status, 0) + 1
            details = {
                "schedule_a_individuals": int(row["schedule_a_individuals"]),
                "schedule_b_individuals": int(row["schedule_b_individuals"]),
                "entity_principals": int(row["entity_principals"]),
            }
            output.append(
                (row["firm_id"], dataset_version, row["snapshot_id"], status,
                 row["representative_count"],
                 int(row["schedule_a_individuals"]) + int(row["schedule_b_individuals"]),
                 int(row["entity_principals"]), row["state_iar_count"],
                 json.dumps(details), now)
            )
        with connection.transaction():
            with connection.cursor() as cursor:
                cursor.executemany(
                    """INSERT INTO iapd_firm_coverage
                       (firm_id,dataset_version,snapshot_id,coverage_status,
                        representative_count,individual_principal_count,
                        entity_principal_count,reported_state_iar_count,details,updated_at)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (firm_id,dataset_version) DO UPDATE SET
                         snapshot_id=EXCLUDED.snapshot_id,
                         coverage_status=EXCLUDED.coverage_status,
                         representative_count=EXCLUDED.representative_count,
                         individual_principal_count=EXCLUDED.individual_principal_count,
                         entity_principal_count=EXCLUDED.entity_principal_count,
                         reported_state_iar_count=EXCLUDED.reported_state_iar_count,
                         details=EXCLUDED.details,updated_at=EXCLUDED.updated_at""",
                    output,
                )
    return {"dataset_version": dataset_version, "firms": len(output), "status_counts": counts}


def main() -> None:
    parser = argparse.ArgumentParser(description="Form ADV principal and IAPD coverage tools")
    subparsers = parser.add_subparsers(dest="command", required=True)
    principals = subparsers.add_parser("import-principals")
    principals.add_argument("--database-url", required=True)
    principals.add_argument("--source", type=Path, required=True)
    principals.add_argument("--source-url")
    coverage = subparsers.add_parser("refresh-coverage")
    coverage.add_argument("--database-url", required=True)
    args = parser.parse_args()
    result = (
        import_adv_principals(
            args.source, database_url=args.database_url, source_url=args.source_url
        )
        if args.command == "import-principals"
        else refresh_iapd_firm_coverage(database_url=args.database_url)
    )
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()

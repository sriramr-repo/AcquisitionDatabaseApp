"""Monthly IAPD individual-representative snapshot ingestion.

The SEC IAPD compilation report is a monthly person-level snapshot.  It is
intentionally kept separate from the Form ADV firm universe: the local
DuckDB/SQLite pipeline remains authoritative for firm facts and this module
publishes normalized representative enrichment to the dashboard PostgreSQL
database only.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import tempfile
import time
import zipfile
from collections import Counter
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Iterable, Iterator
from xml.etree import ElementTree as ET

import requests
from lxml import etree as LET

from src.config import settings


log = logging.getLogger(__name__)

IAPD_COMPILATION_URL = (
    "https://reports.adviserinfo.sec.gov/reports/CompilationReports/"
    "IA_INDVL_Feed_{month:02d}_{day:02d}_{year:04d}.xml.zip"
)
IAPD_BROWSER_URL = "https://adviserinfo.sec.gov/compilation"
DISCLOSURE_FIELDS = (
    "reg_action", "criminal", "bankrupt", "civil_judgment", "bond",
    "judgment", "investigation", "customer_complaint", "termination",
)


class IAPDFeedUnavailable(RuntimeError):
    """The requested monthly IAPD compilation feed could not be retrieved."""


def build_iapd_feed_url(snapshot_date: date) -> str:
    """Construct the SEC IAPD compilation-feed URL for one snapshot date."""
    return IAPD_COMPILATION_URL.format(
        month=snapshot_date.month, day=snapshot_date.day, year=snapshot_date.year
    )


def _local_name(element: ET.Element) -> str:
    return element.tag.rsplit("}", 1)[-1].lower()


def _clean(value: str | None) -> str | None:
    if value is None:
        return None
    value = " ".join(value.replace("\u00a0", " ").split())
    if not value or value.casefold() in {"n/a", "na", "none", "null", "unknown", "-", "--"}:
        return None
    return value


def _text(element: ET.Element | None, *names: str) -> str | None:
    if element is None:
        return None
    candidates = {name.lower() for name in names}
    for child in element.iter():
        if _local_name(child) in candidates:
            return _clean(child.text)
    attributes = {key.lower(): value for key, value in element.attrib.items()}
    for name in candidates:
        if name in attributes:
            return _clean(attributes[name])
    return None


def _children_named(element: ET.Element | None, names: Iterable[str]) -> list[ET.Element]:
    if element is None:
        return []
    targets = {name.lower() for name in names}
    return [child for child in element.iter() if _local_name(child) in targets]


def _collection_records(
    individual: ET.Element, collection_names: Iterable[str], item_names: Iterable[str]
) -> list[ET.Element]:
    collections = _children_named(individual, collection_names)
    items = {name.lower() for name in item_names}
    records: list[ET.Element] = []
    for collection in collections:
        direct = [child for child in list(collection) if _local_name(child) in items]
        if direct:
            records.extend(direct)
        elif _local_name(collection) in items:
            records.append(collection)
    return records


def _bool(value: str | None) -> bool | None:
    if value is None:
        return None
    normalized = value.strip().lower()
    if normalized in {"y", "yes", "true", "t", "1"}:
        return True
    if normalized in {"n", "no", "false", "f", "0"}:
        return False
    return None


def _request_header_profiles() -> list[dict[str, str]]:
    user_agent = settings.USER_AGENT
    return [
        {
            "User-Agent": user_agent,
            "Accept": "application/zip,application/octet-stream;q=0.9,*/*;q=0.8",
            "Referer": IAPD_BROWSER_URL,
        },
        {
            "User-Agent": user_agent,
            "Accept": "application/zip,application/octet-stream;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
            "Referer": IAPD_BROWSER_URL,
        },
        {
            "User-Agent": (
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
            ),
            "Accept": "application/zip,application/octet-stream;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": IAPD_BROWSER_URL,
        },
    ]


def _stable_id(*parts: Any) -> str:
    text = "|".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _address(element: ET.Element) -> dict[str, str | None]:
    return {
        "address_line_1": _text(element, "address1", "addressline1", "street1", "addr1", "str1"),
        "address_line_2": _text(element, "address2", "addressline2", "street2", "addr2", "str2"),
        "city": _text(element, "city"),
        "state": _text(element, "state", "statecode"),
        "postal_code": _text(element, "zipcode", "zip", "postalcode", "postal_code", "postlcd"),
        "country": _text(element, "country", "countrycode", "cntry"),
    }


def _name(element: ET.Element) -> dict[str, str | None]:
    return {
        "first_name": _text(element, "firstname", "firstnm", "fname", "first_name"),
        "middle_name": _text(element, "middlename", "middlenm", "midnm", "mname", "middle_name"),
        "last_name": _text(element, "lastname", "lastnm", "lname", "last_name"),
        "suffix": _text(element, "suffix", "suffixname", "suffixnm", "sufnm"),
    }


def _full_name(parts: dict[str, str | None]) -> str | None:
    return " ".join(part for part in parts.values() if part) or None


def _record_from_individual(individual: ET.Element) -> dict[str, Any] | None:
    info_nodes = _children_named(individual, ("Info", "IndividualInfo"))
    info = info_nodes[0] if info_nodes else individual
    individual_crd = _text(info, "indvlpk", "individualcrd", "crd", "crdnumber")
    if individual_crd is None:
        return None
    name = _name(info)
    return {
        "individual_crd": individual_crd,
        **name,
        "full_name": _full_name(name),
        "active_ag_registration": _bool(_text(info, "activeagregistration", "activeagreg", "activeagregflag", "actvagreg")),
        "composite_link": _text(info, "compositelink", "compositelinkurl", "link"),
    }


def parse_iapd_xml(xml_path: Path | BinaryIO, *, issues: list[dict[str, Any]] | None = None) -> Iterator[dict[str, Any]]:
    """Yield normalized representative records from an IAPD compilation XML file.

    Tag matching is namespace-insensitive and intentionally accepts common
    SEC/FINRA naming variants.  Missing optional collections simply yield
    empty lists.
    """
    context = LET.iterparse(xml_path, events=("end",), recover=False, huge_tree=True)
    for _, element in context:
        if _local_name(element) not in {"indvl", "individual"}:
            continue
        person = _record_from_individual(element)
        if person is None:
            if issues is not None:
                issues.append({"stage": "parse", "severity": "warning", "code": "MISSING_CRD", "message": "Representative record omitted because it has no individual CRD."})
            element.clear()
            parent = element.getparent()
            if parent is not None:
                while element.getprevious() is not None:
                    del parent[0]
            continue
        crd = person["individual_crd"]
        if not person["full_name"] and issues is not None:
            issues.append({"stage": "parse", "severity": "warning", "code": "MISSING_NAME", "individual_crd": crd, "message": "Representative has no usable name fields."})
        aliases = []
        for alias in _collection_records(element, ("OthrNms", "OtherNames"), ("OthrNm", "OtherName", "Name")):
            alias_parts = _name(alias)
            alias_name = _full_name(alias_parts) or _text(alias, "name", "othername")
            if alias_name:
                aliases.append({"alias_name": alias_name, **alias_parts})

        employments = []
        for employment in _collection_records(element, ("CrntEmps", "CurrentEmployments"), ("CrntEmp", "CurrentEmployment", "Employment")):
            employer_crd = _text(employment, "orgpk", "firmcrd", "organizationcrd", "employercrd")
            employer_name = _text(employment, "orgname", "orgnm", "firmname", "employername", "organizationname")
            employment_id = _stable_id(crd, employer_crd, employer_name, "current")
            registrations = []
            for registration in _collection_records(employment, ("CrntRgstns", "CurrentRegistrations"), ("CrntRgstn", "CurrentRegistration", "Registration")):
                registrations.append({
                    "authority": _text(registration, "regauthority", "authority", "regulator", "regauth"),
                    "category": _text(registration, "regcategory", "category", "registrationcategory", "regcat"),
                    "status": _text(registration, "regstatus", "status", "registrationstatus", "st"),
                    "status_date": _text(registration, "statusdate", "regstatusdate", "date", "stdt"),
                })
            branches = []
            for branch in _collection_records(employment, ("BrnchOfcs", "BrnchOfLocs", "BranchOffices", "BranchLocations"), ("BrnchOfc", "BrnchOfLoc", "BranchOffice", "BranchLocation", "Office")):
                branches.append({"branch_name": _text(branch, "branchname", "name"), **_address(branch)})
            employments.append({
                "employment_id": employment_id,
                "employer_firm_crd": employer_crd,
                "employer_name": employer_name,
                **_address(employment),
                "registrations": registrations,
                "branches": branches,
            })

        previous_registrations = []
        for previous in _collection_records(element, ("PrevRgstns", "PreviousRegistrations"), ("PrevRgstn", "PreviousRegistration", "Registration")):
            previous_registrations.append({
                "employer_firm_crd": _text(previous, "orgpk", "firmcrd", "organizationcrd", "employercrd"),
                "employer_name": _text(previous, "orgname", "orgnm", "firmname", "employername", "organizationname"),
                "authority": _text(previous, "regauthority", "authority", "regulator"),
                "category": _text(previous, "regcategory", "category", "registrationcategory"),
                "status": _text(previous, "regstatus", "status", "registrationstatus"),
                "begin_date": _text(previous, "begindate", "registrationbegindate", "fromdate", "from", "regbegindt"),
                "end_date": _text(previous, "enddate", "registrationenddate", "todate", "to", "regenddt"),
                **_address(previous),
            })

        employment_history = []
        for history in _collection_records(element, ("EmpHss", "EmploymentHistories"), ("EmpHs", "EmploymentHistory", "Employment")):
            employment_history.append({
                "organization_name": _text(history, "orgname", "orgnm", "organizationname", "employername", "firmname"),
                "city": _text(history, "city"),
                "state": _text(history, "state", "statecode"),
                "from_date": _text(history, "fromdate", "begindate", "from", "fromdt"),
                "to_date": _text(history, "todate", "enddate", "to", "todt"),
            })

        other_businesses = []
        for business in _collection_records(element, ("OthrBuss", "OtherBusinesses"), ("OthrBus", "OtherBusiness", "Business")):
            description = _text(business, "description", "otherbusinessdescription", "businessdescription", "desc")
            if description:
                other_businesses.append({"description": description})

        disclosures = []
        for disclosure in _collection_records(element, ("DRPs", "Disclosures"), ("DRP", "Disclosure")):
            flags = {
                "reg_action": _bool(_text(disclosure, "regaction", "regactionflag", "hasregaction")),
                "criminal": _bool(_text(disclosure, "criminal", "criminalflag", "hascriminal")),
                "bankrupt": _bool(_text(disclosure, "bankrupt", "bankruptcy", "bankruptflag", "hasbankrupt")),
                "civil_judgment": _bool(_text(disclosure, "civiljudgment", "civiljudgmentflag", "hasciviljudc")),
                "bond": _bool(_text(disclosure, "bond", "bondflag", "hasbond")),
                "judgment": _bool(_text(disclosure, "judgment", "judgmentflag", "hasjudgment")),
                "investigation": _bool(_text(disclosure, "investigation", "investigationflag", "hasinvstgn")),
                "customer_complaint": _bool(_text(disclosure, "customercomplaint", "customercomplaintflag", "complaint", "hascustcomp")),
                "termination": _bool(_text(disclosure, "termination", "terminationflag", "hastermination")),
            }
            disclosures.append(flags)
        yield {
            **person,
            "aliases": aliases,
            "current_employments": employments,
            "previous_registrations": previous_registrations,
            "employment_history": employment_history,
            "other_businesses": other_businesses,
            "disclosures": disclosures,
        }
        # lxml frees prior siblings as the document streams.  The official
        # feed exceeds one GB uncompressed, so this avoids retaining already
        # processed representatives under the root collection.
        element.clear()
        parent = element.getparent()
        if parent is not None:
            while element.getprevious() is not None:
                del parent[0]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_zip(path: Path) -> list[str]:
    if not zipfile.is_zipfile(path):
        raise IAPDFeedUnavailable(f"IAPD download is not a ZIP file: {path}")
    with zipfile.ZipFile(path) as archive:
        members = [item for item in archive.infolist() if not item.is_dir() and item.filename.lower().endswith(".xml")]
        if not members or any(member.file_size == 0 for member in members) or archive.testzip() is not None:
            raise IAPDFeedUnavailable("IAPD ZIP must contain readable XML member(s)")
        return [member.filename for member in members]


def validate_iapd_xml(xml_path: Path) -> None:
    """Fail early for empty or malformed XML before any snapshot write."""
    try:
        root = ET.parse(xml_path).getroot()
    except (ET.ParseError, OSError) as exc:
        raise IAPDFeedUnavailable(f"IAPD XML is malformed or unreadable: {exc}") from exc
    if _local_name(root) not in {"iapd", "individuals", "indvlfeed", "feed"}:
        raise IAPDFeedUnavailable(f"IAPD XML has an unexpected root element: {_local_name(root)}")


def download_iapd_feed(snapshot_date: date, *, session: requests.Session | None = None, retries: int = 3) -> tuple[Path, str, str]:
    """Download and atomically retain an IAPD monthly ZIP artifact."""
    url = build_iapd_feed_url(snapshot_date)
    client = session or requests.Session()
    raw_dir = settings.BASE_DIR / "iapd" / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    filename = f"IA_INDVL_Feed_{snapshot_date:%m_%d_%Y}.xml.zip"
    destination = raw_dir / filename
    error: Exception | None = None
    for attempt in range(retries):
        try:
            for headers in _request_header_profiles():
                response = client.get(url, headers=headers, timeout=settings.TIMEOUT, stream=True)
                if response.status_code == 404:
                    raise IAPDFeedUnavailable(f"IAPD feed is unavailable for {snapshot_date.isoformat()}: HTTP 404")
                if response.status_code == 403:
                    error = IAPDFeedUnavailable("IAPD feed returned HTTP 403")
                    continue
                response.raise_for_status()
                with tempfile.NamedTemporaryFile(dir=raw_dir, suffix=".zip", delete=False) as temporary:
                    temporary_path = Path(temporary.name)
                    for chunk in response.iter_content(chunk_size=1024 * 1024):
                        if chunk:
                            temporary.write(chunk)
                _validate_zip(temporary_path)
                os.replace(temporary_path, destination)
                return destination, url, _sha256(destination)
            if isinstance(error, IAPDFeedUnavailable):
                raise error
        except (requests.RequestException, IAPDFeedUnavailable, zipfile.BadZipFile) as exc:
            error = exc
            if "temporary_path" in locals() and temporary_path.exists():
                temporary_path.unlink()
            if isinstance(exc, IAPDFeedUnavailable) or attempt == retries - 1:
                break
            time.sleep(2**attempt)
    raise IAPDFeedUnavailable(f"Unable to retrieve IAPD feed {url}: {error}")


def extract_iapd_xml(zip_path: Path) -> Path:
    """Extract the validated XML beside its raw ZIP without mutating the ZIP."""
    members = _validate_zip(zip_path)
    if len(members) != 1:
        raise IAPDFeedUnavailable("Multi-part IAPD ZIPs are imported by streaming; they are not extracted to disk")
    member = members[0]
    destination = zip_path.with_suffix("")
    with zipfile.ZipFile(zip_path) as archive, tempfile.NamedTemporaryFile(
        dir=zip_path.parent, suffix=".xml", delete=False
    ) as temporary:
        with archive.open(member) as source:
            while chunk := source.read(1024 * 1024):
                temporary.write(chunk)
        temporary_path = Path(temporary.name)
    os.replace(temporary_path, destination)
    return destination


def parse_iapd_zip(
    zip_path: Path,
    *,
    issues: list[dict[str, Any]] | None = None,
    member_names: Iterable[str] | None = None,
) -> Iterator[dict[str, Any]]:
    """Stream every XML member in a compilation ZIP without a large extraction."""
    members = _validate_zip(zip_path)
    if member_names is not None:
        requested = set(member_names)
        unknown = requested.difference(members)
        if unknown:
            raise IAPDFeedUnavailable(f"IAPD ZIP does not contain requested XML member(s): {', '.join(sorted(unknown))}")
        members = [member for member in members if member in requested]
    with zipfile.ZipFile(zip_path) as archive:
        for member in members:
            try:
                with archive.open(member) as stream:
                    yield from parse_iapd_xml(stream, issues=issues)
            except ET.ParseError as exc:
                if issues is not None:
                    issues.append({"stage": "parse", "severity": "error", "code": "MALFORMED_XML_MEMBER", "message": f"{member}: {exc}"})
                raise IAPDFeedUnavailable(f"IAPD XML member is malformed: {member}") from exc


def _dashboard_firm_crds(connection: Any, *, priority_categories: Iterable[str] | None = None) -> set[str]:
    """Return current dashboard firm CRDs, optionally limited to priorities.

    The full SEC compilation feed remains in the local raw archive.  Hosted
    PostgreSQL receives only the representatives relevant to the dashboard so
    the application database does not become a second, unbounded IAPD store.
    """
    if priority_categories:
        categories = tuple(priority_categories)
        rows = connection.execute(
            """SELECT f.firm_id
               FROM firms f JOIN firm_scores s USING (firm_id, dataset_version)
               WHERE f.dataset_version=(SELECT dataset_version FROM dataset_versions ORDER BY published_at DESC LIMIT 1)
                 AND s.priority_category = ANY(%s)""",
            (list(categories),),
        ).fetchall()
    else:
        rows = connection.execute(
            """SELECT firm_id FROM firms
               WHERE dataset_version=(SELECT dataset_version FROM dataset_versions ORDER BY published_at DESC LIMIT 1)"""
        ).fetchall()
    return {str(row[0]) for row in rows if row and row[0] is not None}


def inspect_iapd_scope(zip_path: Path, firm_crds: set[str]) -> dict[str, int]:
    """Read a ZIP once and report the hosted footprint without writing data."""
    summary: Counter[str] = Counter()
    for person in parse_iapd_zip(zip_path):
        matched = [employment for employment in person["current_employments"] if employment["employer_firm_crd"] in firm_crds]
        if not matched:
            continue
        summary["individuals"] += 1
        summary["current_employments"] += len(matched)
        summary["current_registrations"] += sum(len(item["registrations"]) for item in matched)
        summary["aliases"] += len(person["aliases"])
        summary["employment_history"] += len(person["employment_history"])
        summary["previous_registrations"] += len(person["previous_registrations"])
        summary["other_businesses"] += len(person["other_businesses"])
        summary["disclosures"] += len(person["disclosures"])
    return dict(summary)


def _empty_firm_summary() -> dict[str, Any]:
    return {
        "representative_count": 0,
        "active_representative_count": 0,
        "representative_with_disclosure_count": 0,
        "representative_with_other_business_count": 0,
        "registration_count": 0,
        "registration_status_counts": Counter(),
    }


def _summarize_iapd_people(
    people: Iterable[dict[str, Any]], target_firms: set[str]
) -> dict[str, dict[str, Any]]:
    """Return unique firm/person counts for one complete feed or ZIP member."""
    summaries: dict[str, dict[str, Any]] = {}
    seen: set[tuple[str, str]] = set()
    for person in people:
        disclosed = any(
            any(item.get(field) is True for field in DISCLOSURE_FIELDS)
            for item in person["disclosures"]
        )
        other_business = bool(person["other_businesses"])
        for employment in person["current_employments"]:
            firm_id = employment["employer_firm_crd"]
            key = (firm_id or "", person["individual_crd"])
            if firm_id not in target_firms or key in seen:
                continue
            seen.add(key)
            summary = summaries.setdefault(firm_id, _empty_firm_summary())
            summary["representative_count"] += 1
            summary["active_representative_count"] += int(
                person["active_ag_registration"] is True
            )
            summary["representative_with_disclosure_count"] += int(disclosed)
            summary["representative_with_other_business_count"] += int(other_business)
            summary["registration_count"] += len(employment["registrations"])
            for registration in employment["registrations"]:
                if status := registration.get("status"):
                    summary["registration_status_counts"][status] += 1
    return summaries


def _merge_firm_summary(
    target: dict[str, Any], source: dict[str, Any]
) -> None:
    for field in (
        "representative_count",
        "active_representative_count",
        "representative_with_disclosure_count",
        "representative_with_other_business_count",
        "registration_count",
    ):
        target[field] += int(source.get(field) or 0)
    statuses = source.get("registration_status_counts") or {}
    if isinstance(statuses, str):
        statuses = json.loads(statuses)
    target["registration_status_counts"].update(statuses)


def import_iapd_firm_summaries(
    *, snapshot_date: date, source_url: str, source_zip: Path, database_url: str,
    member_names: Iterable[str] | None = None, finalize: bool = True,
    content_hash: str | None = None,
) -> dict[str, Any]:
    """Publish a compact current IAPD coverage record for every dashboard firm.

    This is intentionally separate from the detailed representative tables:
    all firm CRDs receive a lightweight summary, while full people/history
    records remain a targeted research workflow.
    """
    import psycopg

    content_hash = content_hash or _sha256(source_zip)
    snapshot_id = _stable_id(snapshot_date.isoformat(), content_hash)
    selected_members = tuple(member_names) if member_names is not None else None
    partial_batch = selected_members is not None and not finalize
    with psycopg.connect(database_url) as connection:
        target_firms = _dashboard_firm_crds(connection)
        if not target_firms:
            raise IAPDFeedUnavailable("No current dashboard firms are available for IAPD summary publication")
        if partial_batch:
            if len(selected_members) != 1:
                raise ValueError("partial IAPD summary publication requires exactly one ZIP member")
            summaries = _summarize_iapd_people(
                parse_iapd_zip(source_zip, member_names=selected_members), target_firms
            )
        elif selected_members == ():
            summaries = {firm_id: _empty_firm_summary() for firm_id in target_firms}
            staged = connection.execute(
                """SELECT firm_id,representative_count,active_representative_count,
                          representative_with_disclosure_count,
                          representative_with_other_business_count,registration_count,
                          registration_status_counts
                     FROM iapd_firm_summary_batch_counts WHERE snapshot_id=%s""",
                (snapshot_id,),
            ).fetchall()
            for row in staged:
                values = {
                    "representative_count": row[1],
                    "active_representative_count": row[2],
                    "representative_with_disclosure_count": row[3],
                    "representative_with_other_business_count": row[4],
                    "registration_count": row[5],
                    "registration_status_counts": row[6],
                }
                _merge_firm_summary(summaries.setdefault(str(row[0]), _empty_firm_summary()), values)
        else:
            summaries = {firm_id: _empty_firm_summary() for firm_id in target_firms}
            direct = _summarize_iapd_people(
                parse_iapd_zip(source_zip, member_names=selected_members), target_firms
            )
            for firm_id, values in direct.items():
                _merge_firm_summary(summaries[firm_id], values)
        now = datetime.now(timezone.utc)
        rows = [
            (snapshot_id, snapshot_date.isoformat(), firm_id, source_url, content_hash,
             values["representative_count"], values["active_representative_count"],
             values["representative_with_disclosure_count"], values["representative_with_other_business_count"],
             values["registration_count"], json.dumps(dict(values["registration_status_counts"])), now)
            for firm_id, values in summaries.items()
        ]
        with connection.transaction():
            if partial_batch:
                connection.execute(
                    """INSERT INTO iapd_firm_summary_batches (snapshot_id,member_name,processed_at)
                       VALUES (%s,%s,%s) ON CONFLICT (snapshot_id,member_name)
                       DO UPDATE SET processed_at=EXCLUDED.processed_at""",
                    (snapshot_id, selected_members[0], now),
                )
                connection.execute(
                    "DELETE FROM iapd_firm_summary_batch_counts WHERE snapshot_id=%s AND member_name=%s",
                    (snapshot_id, selected_members[0]),
                )
                batch_rows = [
                    (snapshot_id, selected_members[0], firm_id,
                     values["representative_count"], values["active_representative_count"],
                     values["representative_with_disclosure_count"],
                     values["representative_with_other_business_count"],
                     values["registration_count"],
                     json.dumps(dict(values["registration_status_counts"])), now)
                    for firm_id, values in summaries.items()
                ]
                _execute_many(connection, """INSERT INTO iapd_firm_summary_batch_counts
                    (snapshot_id,member_name,firm_id,representative_count,active_representative_count,
                     representative_with_disclosure_count,representative_with_other_business_count,
                     registration_count,registration_status_counts,processed_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""", batch_rows)
            else:
                _execute_many(connection, """INSERT INTO iapd_firm_summaries
                (snapshot_id,snapshot_date,firm_id,source_url,content_hash,representative_count,active_representative_count,representative_with_disclosure_count,representative_with_other_business_count,registration_count,registration_status_counts,published_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (snapshot_id,firm_id) DO UPDATE SET
                  snapshot_date=EXCLUDED.snapshot_date,source_url=EXCLUDED.source_url,
                  content_hash=EXCLUDED.content_hash,
                  representative_count=EXCLUDED.representative_count,
                  active_representative_count=EXCLUDED.active_representative_count,
                  representative_with_disclosure_count=EXCLUDED.representative_with_disclosure_count,
                  representative_with_other_business_count=EXCLUDED.representative_with_other_business_count,
                  registration_count=EXCLUDED.registration_count,
                  registration_status_counts=EXCLUDED.registration_status_counts,
                  published_at=EXCLUDED.published_at""", rows)
                # Member rows are restart checkpoints, not historical facts.
                # Once the exact summary is committed they only consume hosted
                # database capacity and can be regenerated from the raw ZIP.
                connection.execute(
                    "DELETE FROM iapd_firm_summary_batch_counts WHERE snapshot_id=%s",
                    (snapshot_id,),
                )
        covered = connection.execute(
            "SELECT COUNT(*) FROM iapd_firm_summaries WHERE snapshot_id=%s AND representative_count>0",
            (snapshot_id,),
        ).fetchone()[0]
        return {"status": "success" if finalize else "partial", "snapshot_id": snapshot_id, "firm_count": len(rows), "firms_with_representatives": covered}


def _execute_many(connection: Any, statement: str, rows: list[tuple[Any, ...]]) -> None:
    if rows:
        # psycopg 3 exposes executemany on cursors; the lightweight test
        # doubles used by this project may expose it directly on connection.
        if hasattr(connection, "executemany"):
            connection.executemany(statement, rows)
        else:
            with connection.cursor() as cursor:
                cursor.executemany(statement, rows)


def _change_summary(connection: Any, snapshot_id: str) -> dict[str, int]:
    rows = connection.execute(
        "SELECT event_type, COUNT(*) FROM iapd_individual_changes WHERE snapshot_id=%s GROUP BY event_type",
        (snapshot_id,),
    ).fetchall()
    return {str(event_type): int(count) for event_type, count in rows}


def _record_changes(connection: Any, snapshot_id: str, previous_snapshot_id: str | None) -> None:
    if previous_snapshot_id is None:
        connection.execute(
            """INSERT INTO iapd_individual_changes (change_id,snapshot_id,individual_crd,event_type,details)
               SELECT md5(%s || '|' || individual_crd || '|NEW_INDIVIDUAL'), %s, individual_crd,
                      'NEW_INDIVIDUAL', '{}'::jsonb
                 FROM iapd_individual_snapshot_members WHERE snapshot_id=%s""",
            (snapshot_id, snapshot_id, snapshot_id),
        )
        return
    connection.execute(
        """INSERT INTO iapd_individual_changes (change_id,snapshot_id,individual_crd,event_type,details)
           SELECT md5(%s || '|' || current.individual_crd || '|NEW_INDIVIDUAL'), %s, current.individual_crd,
                  'NEW_INDIVIDUAL', '{}'::jsonb
             FROM iapd_individual_snapshot_members current
             LEFT JOIN iapd_individual_snapshot_members previous
               ON previous.snapshot_id=%s AND previous.individual_crd=current.individual_crd
            WHERE current.snapshot_id=%s AND previous.individual_crd IS NULL""",
        (snapshot_id, snapshot_id, previous_snapshot_id, snapshot_id),
    )
    connection.execute(
        """INSERT INTO iapd_individual_changes (change_id,snapshot_id,individual_crd,event_type,details)
           SELECT md5(%s || '|' || previous.individual_crd || '|DISAPPEARED_INDIVIDUAL'), %s, previous.individual_crd,
                  'DISAPPEARED_INDIVIDUAL', '{}'::jsonb
             FROM iapd_individual_snapshot_members previous
             LEFT JOIN iapd_individual_snapshot_members current
               ON current.snapshot_id=%s AND current.individual_crd=previous.individual_crd
            WHERE previous.snapshot_id=%s AND current.individual_crd IS NULL""",
        (snapshot_id, snapshot_id, snapshot_id, previous_snapshot_id),
    )
    connection.execute(
        """INSERT INTO iapd_individual_changes (change_id,snapshot_id,individual_crd,event_type,details)
           WITH current_employers AS (
             SELECT individual_crd, array_agg(DISTINCT coalesce(employer_firm_crd, employer_name, '')) AS employers
               FROM iapd_individual_current_employments WHERE snapshot_id=%s GROUP BY individual_crd
           ), previous_employers AS (
             SELECT individual_crd, array_agg(DISTINCT coalesce(employer_firm_crd, employer_name, '')) AS employers
               FROM iapd_individual_current_employments WHERE snapshot_id=%s GROUP BY individual_crd
           )
           SELECT md5(%s || '|' || current.individual_crd || '|EMPLOYER_CHANGE'), %s, current.individual_crd,
                  'EMPLOYER_CHANGE', jsonb_build_object('previous_employers', previous.employers, 'current_employers', current.employers)
             FROM current_employers current JOIN previous_employers previous USING (individual_crd)
            WHERE current.employers IS DISTINCT FROM previous.employers""",
        (snapshot_id, previous_snapshot_id, snapshot_id, snapshot_id),
    )
    connection.execute(
        """INSERT INTO iapd_individual_changes (change_id,snapshot_id,individual_crd,event_type,details)
           SELECT md5(%s || '|' || current.individual_crd || '|REGISTRATION_STATUS_CHANGE'), %s, current.individual_crd,
                  'REGISTRATION_STATUS_CHANGE', jsonb_build_object('authority', current.authority, 'category', current.category, 'previous_status', previous.status, 'current_status', current.status)
             FROM iapd_individual_current_registrations current
             JOIN iapd_individual_current_registrations previous
               ON previous.snapshot_id=%s AND previous.individual_crd=current.individual_crd
              AND coalesce(previous.authority,'')=coalesce(current.authority,'')
              AND coalesce(previous.category,'')=coalesce(current.category,'')
            WHERE current.snapshot_id=%s
              AND coalesce(current.status,'') <> coalesce(previous.status,'')""",
        (snapshot_id, snapshot_id, previous_snapshot_id, snapshot_id),
    )
    connection.execute(
        """INSERT INTO iapd_individual_changes (change_id,snapshot_id,individual_crd,event_type,details)
           SELECT md5(%s || '|' || current.individual_crd || '|EMPLOYMENT_HISTORY_CHANGE'), %s, current.individual_crd,
                  'EMPLOYMENT_HISTORY_CHANGE', jsonb_build_object('organization_name', current.organization_name, 'from_date', current.from_date, 'to_date', current.to_date)
             FROM iapd_individual_employment_history current
             JOIN iapd_individual_snapshot_members previous_member
               ON previous_member.snapshot_id=%s AND previous_member.individual_crd=current.individual_crd
            WHERE current.snapshot_id=%s
              AND NOT EXISTS (
                SELECT 1 FROM iapd_individual_employment_history previous
                 WHERE previous.snapshot_id=%s AND previous.individual_crd=current.individual_crd
                   AND coalesce(previous.organization_name,'')=coalesce(current.organization_name,'')
                   AND coalesce(previous.city,'')=coalesce(current.city,'')
                   AND coalesce(previous.state,'')=coalesce(current.state,'')
                   AND coalesce(previous.from_date,'')=coalesce(current.from_date,'')
                   AND coalesce(previous.to_date,'')=coalesce(current.to_date,'')
              )""",
        (snapshot_id, snapshot_id, previous_snapshot_id, snapshot_id, previous_snapshot_id),
    )
    connection.execute(
        """INSERT INTO iapd_individual_changes (change_id,snapshot_id,individual_crd,event_type,details)
           SELECT md5(%s || '|' || current.individual_crd || '|NEW_DISCLOSURE'), %s, current.individual_crd,
                  'NEW_DISCLOSURE', to_jsonb(current)
             FROM iapd_individual_disclosure_flags current
             JOIN iapd_individual_disclosure_flags previous ON previous.individual_crd=current.individual_crd AND previous.snapshot_id=%s
            WHERE current.snapshot_id=%s AND (
              (current.reg_action AND NOT coalesce(previous.reg_action,false)) OR
              (current.criminal AND NOT coalesce(previous.criminal,false)) OR
              (current.bankrupt AND NOT coalesce(previous.bankrupt,false)) OR
              (current.civil_judgment AND NOT coalesce(previous.civil_judgment,false)) OR
              (current.bond AND NOT coalesce(previous.bond,false)) OR
              (current.judgment AND NOT coalesce(previous.judgment,false)) OR
              (current.investigation AND NOT coalesce(previous.investigation,false)) OR
              (current.customer_complaint AND NOT coalesce(previous.customer_complaint,false)) OR
              (current.termination AND NOT coalesce(previous.termination,false))
            )""",
        (snapshot_id, snapshot_id, previous_snapshot_id, snapshot_id),
    )


def import_iapd_snapshot(
    xml_path: Path | None,
    *,
    snapshot_date: date,
    source_url: str,
    source_zip: Path,
    database_url: str,
    dashboard_only: bool = True,
    priority_categories: Iterable[str] | None = None,
    target_firm_crds: Iterable[str] | None = None,
    member_names: Iterable[str] | None = None,
    finalize: bool = True,
    expand_existing: bool = False,
) -> dict[str, Any]:
    """Normalize one IAPD snapshot into PostgreSQL, scoped to dashboard firms.

    ``dashboard_only`` is the production-safe default.  It avoids replicating
    the complete national representative feed into the application database;
    the unmodified ZIP remains the local authoritative raw artifact.
    """
    import psycopg

    content_hash = _sha256(source_zip)
    snapshot_id = _stable_id(snapshot_date.isoformat(), content_hash)
    if xml_path is not None:
        validate_iapd_xml(xml_path)
    with psycopg.connect(database_url) as connection:
        existing = connection.execute(
            "SELECT snapshot_id, status, individual_count FROM iapd_individual_snapshots WHERE content_hash=%s OR snapshot_date=%s",
            (content_hash, snapshot_date.isoformat()),
        ).fetchone()
        if existing:
            # A prior parser-version failure can leave a SUCCESS/zero-row
            # snapshot. It has no normalized members and is safe to replace
            # through the normal import path after parser correction.
            existing_count = existing[2] if len(existing) > 2 else None
            if str(existing[1]) == "SUCCESS" and existing_count == 0:
                connection.execute("DELETE FROM iapd_import_issues WHERE snapshot_id=%s", (existing[0],))
                connection.execute("DELETE FROM iapd_individual_snapshots WHERE snapshot_id=%s", (existing[0],))
                # Commit this normal importer cleanup before starting the new
                # snapshot transaction; otherwise a later import rollback
                # would restore the obsolete zero-row marker.
                connection.commit()
            elif str(existing[1]) == "RUNNING":
                snapshot_id = str(existing[0])
            elif expand_existing and str(existing[1]) == "SUCCESS":
                snapshot_id = str(existing[0])
            else:
                return {"status": "skipped", "snapshot_id": str(existing[0]), "reason": "duplicate_snapshot"}
        if dashboard_only:
            dashboard_firms = _dashboard_firm_crds(
                connection, priority_categories=priority_categories
            )
            selected_firms = (
                dashboard_firms.intersection(str(value) for value in target_firm_crds)
                if target_firm_crds is not None else dashboard_firms
            )
        else:
            selected_firms = None
        if dashboard_only and not selected_firms:
            raise IAPDFeedUnavailable("No current dashboard firms are available for a scoped IAPD import")
        previous = connection.execute(
            "SELECT snapshot_id FROM iapd_individual_snapshots WHERE status='SUCCESS' ORDER BY snapshot_date DESC LIMIT 1"
        ).fetchone()
        previous_snapshot_id = str(previous[0]) if previous else None
        now = datetime.now(timezone.utc)
        counts: Counter[str] = Counter()
        with connection.transaction():
            if not existing or (str(existing[1]) == "SUCCESS" and existing_count == 0):
                connection.execute(
                """INSERT INTO iapd_individual_snapshots
                   (snapshot_id,snapshot_date,source_url,source_file_name,source_zip_path,content_hash,status,downloaded_at,parsed_at,created_at,updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,'RUNNING',%s,%s,%s,%s)""",
                (snapshot_id, snapshot_date.isoformat(), source_url, source_zip.name, str(source_zip), content_hash, now, now, now, now),
                )
            people_rows: list[tuple[Any, ...]] = []
            members: list[tuple[Any, ...]] = []
            aliases: list[tuple[Any, ...]] = []
            employments: list[tuple[Any, ...]] = []
            registrations: list[tuple[Any, ...]] = []
            branches: list[tuple[Any, ...]] = []
            previous_regs: list[tuple[Any, ...]] = []
            histories: list[tuple[Any, ...]] = []
            businesses: list[tuple[Any, ...]] = []
            disclosures: list[tuple[Any, ...]] = []
            issues: list[dict[str, Any]] = []
            seen_crds: set[str] = set()

            def flush_batch() -> None:
                """Persist bounded streaming batches; the real feed is multi-GB."""
                _execute_many(connection, """INSERT INTO iapd_individuals (individual_crd,first_name,middle_name,last_name,suffix,full_name,active_ag_registration,composite_link,last_snapshot_id,created_at,updated_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT (individual_crd) DO UPDATE SET first_name=EXCLUDED.first_name,middle_name=EXCLUDED.middle_name,last_name=EXCLUDED.last_name,suffix=EXCLUDED.suffix,full_name=EXCLUDED.full_name,active_ag_registration=EXCLUDED.active_ag_registration,composite_link=EXCLUDED.composite_link,last_snapshot_id=EXCLUDED.last_snapshot_id,updated_at=EXCLUDED.updated_at""", people_rows)
                _execute_many(connection, "INSERT INTO iapd_individual_snapshot_members (snapshot_id,individual_crd,created_at) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING", members)
                _execute_many(connection, "INSERT INTO iapd_individual_aliases (alias_id,snapshot_id,individual_crd,alias_name,first_name,middle_name,last_name,suffix,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", aliases)
                _execute_many(connection, "INSERT INTO iapd_individual_current_employments (employment_id,snapshot_id,individual_crd,employer_firm_crd,employer_name,address_line_1,address_line_2,city,state,postal_code,country,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", employments)
                _execute_many(connection, "INSERT INTO iapd_individual_current_registrations (registration_id,snapshot_id,employment_id,individual_crd,authority,category,status,status_date,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", registrations)
                _execute_many(connection, "INSERT INTO iapd_individual_branch_locations (branch_id,snapshot_id,employment_id,individual_crd,employer_firm_crd,branch_name,address_line_1,address_line_2,city,state,postal_code,country,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", branches)
                _execute_many(connection, "INSERT INTO iapd_individual_previous_registrations (previous_registration_id,snapshot_id,individual_crd,employer_firm_crd,employer_name,authority,category,status,begin_date,end_date,address_line_1,address_line_2,city,state,postal_code,country,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", previous_regs)
                _execute_many(connection, "INSERT INTO iapd_individual_employment_history (history_id,snapshot_id,individual_crd,organization_name,city,state,from_date,to_date,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", histories)
                _execute_many(connection, "INSERT INTO iapd_individual_other_businesses (other_business_id,snapshot_id,individual_crd,description,created_at) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", businesses)
                _execute_many(connection, "INSERT INTO iapd_individual_disclosure_flags (disclosure_id,snapshot_id,individual_crd,reg_action,criminal,bankrupt,civil_judgment,bond,judgment,investigation,customer_complaint,termination,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", disclosures)
                for rows in (people_rows, members, aliases, employments, registrations, branches, previous_regs, histories, businesses, disclosures):
                    rows.clear()
            people = parse_iapd_xml(xml_path, issues=issues) if xml_path is not None else parse_iapd_zip(source_zip, issues=issues, member_names=member_names)
            for person in people:
                if selected_firms is not None:
                    person["current_employments"] = [
                        employment for employment in person["current_employments"]
                        if employment["employer_firm_crd"] in selected_firms
                    ]
                    if not person["current_employments"]:
                        continue
                crd = person["individual_crd"]
                if crd in seen_crds:
                    issues.append({"stage": "normalize", "severity": "warning", "code": "DUPLICATE_INDIVIDUAL", "individual_crd": crd, "message": "Duplicate representative record in the same snapshot was skipped."})
                    continue
                seen_crds.add(crd)
                people_rows.append((crd, person["first_name"], person["middle_name"], person["last_name"], person["suffix"], person["full_name"], person["active_ag_registration"], person["composite_link"], snapshot_id, now, now))
                members.append((snapshot_id, crd, now))
                counts["individuals"] += 1
                if selected_firms is None:
                    for alias in person["aliases"]:
                        aliases.append((_stable_id(snapshot_id, crd, alias["alias_name"]), snapshot_id, crd, alias["alias_name"], alias["first_name"], alias["middle_name"], alias["last_name"], alias["suffix"], now))
                for employment in person["current_employments"]:
                    # Each feed is a distinct monthly snapshot, so dependent
                    # records need a snapshot-scoped employment identifier.
                    employment_id = _stable_id(snapshot_id, employment["employment_id"])
                    employments.append((employment_id, snapshot_id, crd, employment["employer_firm_crd"], employment["employer_name"], employment["address_line_1"], employment["address_line_2"], employment["city"], employment["state"], employment["postal_code"], employment["country"], now))
                    for registration in employment["registrations"]:
                        registrations.append((_stable_id(snapshot_id, employment_id, registration["authority"], registration["category"], registration["status"], registration["status_date"]), snapshot_id, employment_id, crd, registration["authority"], registration["category"], registration["status"], registration["status_date"], now))
                    # Branch records are intentionally not published in
                    # scoped mode.  They are high-cardinality location data
                    # with no current dashboard consumer; the raw ZIP retains
                    # them if needed for a future, dedicated workflow.
                    if selected_firms is None:
                        for branch in employment["branches"]:
                            branches.append((_stable_id(snapshot_id, employment_id, branch["branch_name"], branch["address_line_1"], branch["city"], branch["state"]), snapshot_id, employment_id, crd, employment["employer_firm_crd"], branch["branch_name"], branch["address_line_1"], branch["address_line_2"], branch["city"], branch["state"], branch["postal_code"], branch["country"], now))
                if selected_firms is None:
                    for registration in person["previous_registrations"]:
                        previous_regs.append((_stable_id(snapshot_id, crd, registration["employer_firm_crd"], registration["authority"], registration["begin_date"], registration["end_date"]), snapshot_id, crd, registration["employer_firm_crd"], registration["employer_name"], registration["authority"], registration["category"], registration["status"], registration["begin_date"], registration["end_date"], registration["address_line_1"], registration["address_line_2"], registration["city"], registration["state"], registration["postal_code"], registration["country"], now))
                    for history in person["employment_history"]:
                        histories.append((_stable_id(snapshot_id, crd, history["organization_name"], history["city"], history["state"], history["from_date"], history["to_date"]), snapshot_id, crd, history["organization_name"], history["city"], history["state"], history["from_date"], history["to_date"], now))
                for business in person["other_businesses"]:
                    businesses.append((_stable_id(snapshot_id, crd, business["description"]), snapshot_id, crd, business["description"], now))
                for index, disclosure in enumerate(person["disclosures"]):
                    disclosures.append((_stable_id(snapshot_id, crd, index), snapshot_id, crd, *(disclosure[field] for field in DISCLOSURE_FIELDS), now))
                if counts["individuals"] % 5_000 == 0:
                    flush_batch()
            flush_batch()
            if selected_firms is not None:
                # The parser sees the national feed even for a bounded firm
                # expansion. Persist only issues tied to selected people plus
                # a small source-level sample; the raw ZIP remains authoritative.
                selected_issues = [
                    issue for issue in issues
                    if issue.get("individual_crd") in seen_crds
                ]
                selected_issues.extend(
                    issue for issue in issues
                    if not issue.get("individual_crd")
                )
                issues = selected_issues[:500]
            issue_rows = [(_stable_id(snapshot_id, member_names and tuple(member_names), index, issue.get("code"), issue.get("individual_crd")), snapshot_id, issue.get("individual_crd"), issue["stage"], issue["severity"], issue["code"], issue["message"], json.dumps(issue), now) for index, issue in enumerate(issues)]
            _execute_many(connection, "INSERT INTO iapd_import_issues (issue_id,snapshot_id,individual_crd,stage,severity,issue_code,message,details,created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING", issue_rows)
            if finalize:
                if expand_existing:
                    summary = {
                        "status": "expanded",
                        "batch_individuals": counts["individuals"],
                        "parse_issues": len(issue_rows),
                    }
                else:
                    _record_changes(connection, snapshot_id, previous_snapshot_id)
                    summary = _change_summary(connection, snapshot_id)
                    summary["parse_issues"] = connection.execute("SELECT COUNT(*) FROM iapd_import_issues WHERE snapshot_id=%s", (snapshot_id,)).fetchone()[0]
                individual_count = connection.execute("SELECT COUNT(*) FROM iapd_individual_snapshot_members WHERE snapshot_id=%s", (snapshot_id,)).fetchone()[0]
                if expand_existing:
                    connection.execute("UPDATE iapd_individual_snapshots SET status='SUCCESS', individual_count=%s, parsed_at=%s, updated_at=%s WHERE snapshot_id=%s", (individual_count, now, now, snapshot_id))
                else:
                    connection.execute("UPDATE iapd_individual_snapshots SET status='SUCCESS', individual_count=%s, change_summary=%s, parsed_at=%s, updated_at=%s WHERE snapshot_id=%s", (individual_count, json.dumps(summary), now, now, snapshot_id))
            else:
                summary = {"status": "running", "batch_individuals": counts["individuals"]}
                connection.execute("UPDATE iapd_individual_snapshots SET individual_count=(SELECT COUNT(*) FROM iapd_individual_snapshot_members WHERE snapshot_id=%s), updated_at=%s WHERE snapshot_id=%s", (snapshot_id, now, snapshot_id))
    return {"status": "success" if finalize else "running", "snapshot_id": snapshot_id, "snapshot_date": snapshot_date.isoformat(), "individuals": counts["individuals"], "changes": summary, "dashboard_only": dashboard_only, "target_firm_count": len(selected_firms or [])}


def repair_iapd_firm_summaries(
    *, snapshot_date: date, source_url: str, source_zip: Path, database_url: str
) -> dict[str, Any]:
    """Recompute exact summary counts from the retained raw ZIP."""
    members = _validate_zip(source_zip)
    content_hash = _sha256(source_zip)
    for member in members:
        import_iapd_firm_summaries(
            snapshot_date=snapshot_date, source_url=source_url, source_zip=source_zip,
            database_url=database_url, member_names=(member,), finalize=False,
            content_hash=content_hash,
        )
    result = import_iapd_firm_summaries(
        snapshot_date=snapshot_date, source_url=source_url, source_zip=source_zip,
        database_url=database_url, member_names=(), finalize=True,
        content_hash=content_hash,
    )
    from src.adv_principals import refresh_iapd_firm_coverage
    result["coverage"] = refresh_iapd_firm_coverage(database_url=database_url)
    return result


def expand_iapd_details(
    *, snapshot_date: date, source_url: str, source_zip: Path, database_url: str,
    priority_categories: Iterable[str] = ("PRIORITY_A", "PRIORITY_B", "PRIORITY_C"),
    limit: int = 250,
    max_representatives: int = 500,
) -> dict[str, Any]:
    """Publish one restartable, deterministic batch of missing firm detail."""
    import psycopg

    if limit < 1 or limit > 1_000:
        raise ValueError("detail expansion limit must be between 1 and 1000")
    if max_representatives < 1 or max_representatives > 5_000:
        raise ValueError("representative budget must be between 1 and 5000")
    content_hash = _sha256(source_zip)
    snapshot_id = _stable_id(snapshot_date.isoformat(), content_hash)
    with psycopg.connect(database_url) as connection:
        dashboard_firms = _dashboard_firm_crds(
            connection, priority_categories=priority_categories
        )
        summary_firms = {
            str(row[0]): int(row[1]) for row in connection.execute(
                """SELECT firm_id,representative_count FROM iapd_firm_summaries
                   WHERE snapshot_id=%s AND representative_count>0""",
                (snapshot_id,),
            ).fetchall()
        }
        candidates = sorted(
            dashboard_firms.intersection(summary_firms),
            key=lambda firm_id: (summary_firms[firm_id], firm_id),
        )
        existing = {
            str(row[0]) for row in connection.execute(
                "SELECT DISTINCT employer_firm_crd FROM iapd_individual_current_employments WHERE snapshot_id=%s",
                (snapshot_id,),
            ).fetchall() if row[0] is not None
        }
    selected: list[str] = []
    representative_total = 0
    for firm_id in candidates:
        if firm_id in existing:
            continue
        firm_representatives = summary_firms[firm_id]
        if representative_total + firm_representatives > max_representatives:
            continue
        selected.append(firm_id)
        representative_total += firm_representatives
        if len(selected) >= limit:
            break
    if not selected:
        return {"status": "complete", "snapshot_id": snapshot_id, "selected_firms": 0}
    result = import_iapd_snapshot(
        None, snapshot_date=snapshot_date, source_url=source_url, source_zip=source_zip,
        database_url=database_url, priority_categories=priority_categories,
        target_firm_crds=selected, expand_existing=True,
    )
    result["selected_firms"] = len(selected)
    result["selected_firm_ids"] = selected
    result["selected_representatives"] = representative_total
    return result


def run_iapd_monthly(
    *,
    database_url: str,
    run_date: date | None = None,
    force: bool = False,
    priority_categories: Iterable[str] = ("PRIORITY_A",),
) -> dict[str, Any]:
    """Download and publish current compact IAPD coverage for all dashboard firms."""
    snapshot_date = run_date or date.today()
    if snapshot_date.day != 4 and not force:
        return {"status": "skipped", "reason": "not_scheduled_day", "snapshot_date": snapshot_date.isoformat()}
    try:
        zip_path, source_url, _ = download_iapd_feed(snapshot_date)
        summary = repair_iapd_firm_summaries(
            snapshot_date=snapshot_date, source_url=source_url,
            source_zip=zip_path, database_url=database_url,
        )
        summary["detail_scope"] = list(priority_categories)
        summary["detail_note"] = "Representative detail remains targeted and on-demand."
        summary["source_zip"] = str(zip_path.resolve())
        summary["source_url"] = source_url
        summary["snapshot_date"] = snapshot_date.isoformat()
        return summary
    except IAPDFeedUnavailable as exc:
        # The individual crawl is deliberately targeted by CRD; a failed
        # monthly feed must not trigger an unbounded crawl or fail the firm
        # publisher that ran before it.
        return {"status": "fallback_required", "reason": "monthly_feed_unavailable", "snapshot_date": snapshot_date.isoformat(), "message": str(exc)}


def import_iapd_from_paths(
    *,
    database_url: str,
    snapshot_date: date,
    source_url: str,
    source_zip: Path | None = None,
    xml_path: Path,
    priority_categories: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Import a manually provided IAPD XML or ZIP artifact."""
    if source_zip is None:
        source_zip = xml_path.with_suffix(".xml.zip")
    if not source_zip.exists():
        raise FileNotFoundError(f"source ZIP not found: {source_zip}")
    return import_iapd_snapshot(
        xml_path,
        snapshot_date=snapshot_date,
        source_url=source_url,
        source_zip=source_zip,
        database_url=database_url,
        priority_categories=priority_categories,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="IAPD individual representative monthly ingestion")
    parser.add_argument("command", choices=("refresh", "repair-summaries", "expand-details"))
    parser.add_argument("--database-url", required=True)
    parser.add_argument("--date", type=date.fromisoformat)
    parser.add_argument("--force", action="store_true", help="Permit a manual run outside the fourth day of the month")
    parser.add_argument("--source-zip", type=Path, help="Use an already-downloaded SEC ZIP instead of fetching")
    parser.add_argument("--xml-path", type=Path, help="Use an already-extracted XML file")
    parser.add_argument("--source-url", help="Override the recorded source URL for a manual import")
    parser.add_argument("--priority", action="append", dest="priorities")
    parser.add_argument("--limit", type=int, default=250)
    parser.add_argument("--max-representatives", type=int, default=500)
    args = parser.parse_args()
    if args.command in {"repair-summaries", "expand-details"}:
        if not args.date or not args.source_zip or not args.source_url:
            parser.error("--date, --source-zip, and --source-url are required")
        result = repair_iapd_firm_summaries(
            snapshot_date=args.date, source_url=args.source_url,
            source_zip=args.source_zip, database_url=args.database_url,
        ) if args.command == "repair-summaries" else expand_iapd_details(
            snapshot_date=args.date, source_url=args.source_url,
            source_zip=args.source_zip, database_url=args.database_url,
            priority_categories=args.priorities or ("PRIORITY_A", "PRIORITY_B", "PRIORITY_C"),
            limit=args.limit,
            max_representatives=args.max_representatives,
        )
        print(json.dumps(result, indent=2, default=str))
        return
    if args.xml_path:
        if not args.date:
            parser.error("--date is required when using --xml-path")
        if not args.source_url:
            parser.error("--source-url is required when using --xml-path")
        print(json.dumps(import_iapd_from_paths(
            database_url=args.database_url,
            snapshot_date=args.date,
            source_url=args.source_url,
            source_zip=args.source_zip,
            xml_path=args.xml_path,
        ), indent=2, default=str))
        return
    print(json.dumps(run_iapd_monthly(database_url=args.database_url, run_date=args.date, force=args.force), indent=2, default=str))


if __name__ == "__main__":
    main()

"""Canonical IAPD firm-compilation discovery, validation, and normalization.

The SEC and state firm feeds are one logical snapshot.  This module never
uses the individual feed to create firms and never treats notice filings as
state registrations.
"""

from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import tempfile
import zipfile
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

import pandas as pd
import requests
import duckdb
from lxml import etree

from src.canonical_models import Firm, FirmOffice, FirmRegistrationRelationship, OfficeType


MANIFEST_URL = "https://reports.adviserinfo.sec.gov/reports/CompilationReports/CompilationReports.manifest.json"
REPORT_HOST = "reports.adviserinfo.sec.gov"
SCHEMA_ARCHIVE_URL = "https://iard.com/sites/iard/files/standalonefiles/firm_compilation.zip"
PARSER_VERSION = "iapd-firm-v1"
MAX_COMPRESSED_BYTES = 256 * 1024 * 1024
MAX_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
_FEED_RE = re.compile(r"^IA_FIRM_(SEC|STATE)_Feed_(\d{2})_(\d{2})_(\d{4})\.xml\.gz$")
_CURRENT_SEC_STATUSES = frozenset({"APPROVED"})
_CURRENT_STATE_STATUSES = frozenset({"APPROVED"})
ACTIVATION_MANIFEST_SCHEMA_VERSION = 1
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_ACTIVATION_COUNT_KEYS = frozenset({
    "sec_feed_rows", "sec_registered_firms", "sec_era_firms",
    "state_feed_rows", "state_registered_firms", "state_era_firms",
    "unique_firms", "registered_firms", "era_only_firms",
    "dual_registered_firms", "registered_with_era_firms",
    "cross_feed_overlap", "relationship_rows", "office_rows",
    "duplicate_crds", "unclassified_firms", "identity_conflicts",
})


class IAPDFirmError(ValueError):
    pass


@dataclass(frozen=True)
class FeedDefinition:
    kind: str
    name: str
    url: str
    snapshot_date: date
    advertised_size: str | None = None


@dataclass(frozen=True)
class FirmFeedPair:
    sec: FeedDefinition
    state: FeedDefinition
    discovery_mode: str
    activation_id: str | None = None
    activation_manifest_hash: str | None = None
    expected_source_hashes: Mapping[str, str] = field(default_factory=dict)
    expected_schema_hashes: Mapping[str, str] = field(default_factory=dict)
    expected_counts: Mapping[str, int] = field(default_factory=dict)
    expected_parser_version: str | None = None
    shadow_report: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.sec.kind != "sec" or self.state.kind != "state":
            raise IAPDFirmError("firm feed pair must contain SEC and state feeds")
        if self.sec.snapshot_date != self.state.snapshot_date:
            raise IAPDFirmError("SEC and state firm feeds must have the same snapshot date")
        if self.discovery_mode not in {"latest_manifest", "pinned_activation_manifest"}:
            raise IAPDFirmError("unknown firm feed discovery mode")

    @property
    def snapshot_date(self) -> date:
        return self.sec.snapshot_date

    @property
    def dataset_version(self) -> str:
        return f"iapdfirm{self.snapshot_date:%Y%m%d}"

    def feeds(self) -> dict[str, FeedDefinition]:
        return {"sec": self.sec, "state": self.state}

    def discovery_record(self) -> dict[str, Any]:
        return {
            "discovery_mode": self.discovery_mode,
            "dataset_version": self.dataset_version,
            "snapshot_date": self.snapshot_date.isoformat(),
            "manifest_url": MANIFEST_URL,
            "sec_feed": {"name": self.sec.name, "url": self.sec.url},
            "state_feed": {"name": self.state.name, "url": self.state.url},
            "activation_id": self.activation_id,
            "activation_manifest_hash": self.activation_manifest_hash,
        }


@dataclass
class IAPDFirmSnapshot:
    dataset_version: str
    snapshot_date: date
    firms: pd.DataFrame
    registrations: pd.DataFrame
    offices: pd.DataFrame
    report: dict[str, Any]


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _official_report_url(name: str) -> str:
    if not _FEED_RE.fullmatch(name):
        raise IAPDFirmError(f"unexpected IAPD firm filename: {name}")
    url = f"https://{REPORT_HOST}/reports/CompilationReports/{name}"
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname != REPORT_HOST:
        raise IAPDFirmError("IAPD firm source must use the official HTTPS report host")
    return url


def _feed_definition(item: dict[str, Any]) -> FeedDefinition | None:
    name = str(item.get("name") or "")
    match = _FEED_RE.fullmatch(name)
    if not match:
        return None
    kind, month, day, year = match.groups()
    snapshot_date = date(int(year), int(month), int(day))
    manifest_date = item.get("date")
    if manifest_date and datetime.strptime(str(manifest_date), "%m/%d/%Y").date() != snapshot_date:
        raise IAPDFirmError(f"manifest date does not match filename: {name}")
    return FeedDefinition(kind.lower(), name, _official_report_url(name), snapshot_date, item.get("size"))


def parse_manifest(payload: dict[str, Any]) -> dict[str, FeedDefinition]:
    feeds: dict[str, FeedDefinition] = {}
    for item in payload.get("files") or []:
        definition = _feed_definition(item)
        if definition is not None:
            if definition.kind in feeds:
                raise IAPDFirmError(f"manifest contains multiple {definition.kind} firm feeds")
            feeds[definition.kind] = definition
    if set(feeds) != {"sec", "state"}:
        raise IAPDFirmError("manifest must contain exactly one SEC and one state firm feed")
    if feeds["sec"].snapshot_date != feeds["state"].snapshot_date:
        raise IAPDFirmError("SEC and state firm feeds must have the same snapshot date")
    return feeds


def discover_manifest(*, session: requests.Session | None = None, timeout: int = 30) -> dict[str, FeedDefinition]:
    client = session or requests.Session()
    response = client.get(MANIFEST_URL, timeout=timeout)
    response.raise_for_status()
    final = urlparse(response.url)
    if final.scheme != "https" or final.hostname != REPORT_HOST or final.path != urlparse(MANIFEST_URL).path:
        raise IAPDFirmError("IAPD manifest redirected away from the official report URL")
    content_type = str(response.headers.get("Content-Type", "")).lower().split(";", 1)[0].strip()
    # The official CloudFront/S3 response currently labels this small JSON
    # object as binary/octet-stream. Keep the allow-list narrow and continue
    # to require the exact pinned HTTPS URL before parsing it.
    if content_type not in {"application/json", "binary/octet-stream", "application/octet-stream"}:
        raise IAPDFirmError("IAPD manifest did not return JSON")
    if len(response.content) > 1024 * 1024:
        raise IAPDFirmError("IAPD manifest exceeds size limit")
    try:
        payload = response.json()
    except (TypeError, ValueError) as exc:
        raise IAPDFirmError("IAPD manifest contains invalid JSON") from exc
    return parse_manifest(payload)


def _required_sha256(value: Any, label: str) -> str:
    normalized = str(value or "").strip().lower()
    if not _SHA256_RE.fullmatch(normalized):
        raise IAPDFirmError(f"{label} must be a SHA-256 value")
    return normalized


def _activation_feed(kind: str, payload: Any, snapshot_date: date) -> tuple[FeedDefinition, str]:
    if not isinstance(payload, dict):
        raise IAPDFirmError(f"activation manifest {kind} feed must be an object")
    name = str(payload.get("name") or "")
    definition = _feed_definition({"name": name, "date": snapshot_date.strftime("%m/%d/%Y")})
    if definition is None or definition.kind != kind:
        raise IAPDFirmError(f"activation manifest has an invalid {kind} filename")
    if payload.get("url") != definition.url:
        raise IAPDFirmError(f"activation manifest {kind} URL is not the canonical official URL")
    return definition, _required_sha256(payload.get("sha256"), f"activation manifest {kind} source hash")


def load_activation_manifest(path: Path) -> FirmFeedPair:
    """Load a reviewed local manifest without accepting caller-supplied source URLs."""
    manifest_path = Path(path)
    if not manifest_path.is_file() or manifest_path.stat().st_size > 1024 * 1024:
        raise IAPDFirmError("activation manifest is missing or exceeds the size limit")
    raw = manifest_path.read_bytes()
    try:
        payload = json.loads(raw)
    except (TypeError, ValueError) as exc:
        raise IAPDFirmError("activation manifest contains invalid JSON") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != ACTIVATION_MANIFEST_SCHEMA_VERSION:
        raise IAPDFirmError("unsupported activation manifest schema version")
    try:
        snapshot_date = date.fromisoformat(str(payload.get("snapshot_date")))
    except ValueError as exc:
        raise IAPDFirmError("activation manifest has an invalid snapshot date") from exc
    dataset_version = f"iapdfirm{snapshot_date:%Y%m%d}"
    if payload.get("dataset_version") != dataset_version:
        raise IAPDFirmError("activation manifest dataset version does not match its snapshot date")
    if payload.get("manifest_url") != MANIFEST_URL:
        raise IAPDFirmError("activation manifest must identify the official compilation manifest")
    activation_id = str(payload.get("activation_id") or "").strip()
    if not activation_id:
        raise IAPDFirmError("activation manifest requires an activation ID")
    feeds = payload.get("feeds")
    if not isinstance(feeds, dict) or set(feeds) != {"sec", "state"}:
        raise IAPDFirmError("activation manifest requires exactly SEC and state feeds")
    sec, sec_hash = _activation_feed("sec", feeds["sec"], snapshot_date)
    state, state_hash = _activation_feed("state", feeds["state"], snapshot_date)
    schemas = payload.get("schemas")
    if not isinstance(schemas, dict) or schemas.get("archive_url") != SCHEMA_ARCHIVE_URL:
        raise IAPDFirmError("activation manifest must identify the official schema archive")
    schema_hashes: dict[str, str] = {}
    for kind, expected_name in (("sec", "IAPDSECBulkFeed.xsd"), ("state", "IAPDStateBulkFeed.xsd")):
        item = schemas.get(kind)
        if not isinstance(item, dict) or item.get("name") != expected_name:
            raise IAPDFirmError(f"activation manifest has an invalid {kind} schema")
        schema_hashes[kind] = _required_sha256(item.get("sha256"), f"activation manifest {kind} schema hash")
    counts = payload.get("expected_counts")
    if not isinstance(counts, dict) or set(counts) != _ACTIVATION_COUNT_KEYS:
        raise IAPDFirmError("activation manifest has incomplete reconciliation counts")
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in counts.values()):
        raise IAPDFirmError("activation manifest reconciliation counts must be non-negative integers")
    parser_version = str(payload.get("parser_version") or "")
    if parser_version != PARSER_VERSION:
        raise IAPDFirmError("activation manifest parser version is not supported by this build")
    shadow_report = payload.get("shadow_report")
    if not isinstance(shadow_report, dict) or not shadow_report.get("report_id") or not shadow_report.get("verified_at"):
        raise IAPDFirmError("activation manifest requires shadow-report provenance")
    try:
        verified_at = datetime.fromisoformat(str(shadow_report["verified_at"]).replace("Z", "+00:00"))
    except ValueError as exc:
        raise IAPDFirmError("activation manifest shadow verification time is invalid") from exc
    if verified_at.tzinfo is None:
        raise IAPDFirmError("activation manifest shadow verification time requires a timezone")
    return FirmFeedPair(
        sec=sec,
        state=state,
        discovery_mode="pinned_activation_manifest",
        activation_id=activation_id,
        activation_manifest_hash=hashlib.sha256(raw).hexdigest(),
        expected_source_hashes={"sec": sec_hash, "state": state_hash},
        expected_schema_hashes=schema_hashes,
        expected_counts=dict(counts),
        expected_parser_version=parser_version,
        shadow_report={"report_id": str(shadow_report["report_id"]), "verified_at": str(shadow_report["verified_at"])},
    )


def resolve_firm_feed_pair(*, activation_manifest: Path | None = None,
                           session: requests.Session | None = None) -> FirmFeedPair:
    if activation_manifest is not None:
        return load_activation_manifest(activation_manifest)
    feeds = discover_manifest(session=session)
    return FirmFeedPair(feeds["sec"], feeds["state"], "latest_manifest")


def validate_artifact_hashes(selection: FirmFeedPair, *, source_hashes: Mapping[str, str],
                             schema_hashes: Mapping[str, str]) -> dict[str, Any]:
    actual_sources = {kind: _required_sha256(source_hashes.get(kind), f"downloaded {kind} source hash")
                      for kind in ("sec", "state")}
    actual_schemas = {kind: _required_sha256(schema_hashes.get(kind), f"downloaded {kind} schema hash")
                      for kind in ("sec", "state")}
    if selection.discovery_mode == "pinned_activation_manifest":
        if actual_sources != dict(selection.expected_source_hashes):
            raise IAPDFirmError("downloaded source hashes differ from the approved activation manifest")
        if actual_schemas != dict(selection.expected_schema_hashes):
            raise IAPDFirmError("downloaded schema hashes differ from the approved activation manifest")
    return {
        "status": "matched_activation_manifest" if selection.activation_id else "observed_latest_manifest",
        "source_hashes": actual_sources,
        "schema_hashes": actual_schemas,
    }


def validate_snapshot_counts(selection: FirmFeedPair, snapshot: "IAPDFirmSnapshot") -> dict[str, Any]:
    if snapshot.snapshot_date != selection.snapshot_date or snapshot.dataset_version != selection.dataset_version:
        raise IAPDFirmError("normalized snapshot identity differs from the selected feed pair")
    if selection.expected_parser_version and snapshot.report.get("parser_version") != selection.expected_parser_version:
        raise IAPDFirmError("normalized snapshot parser version differs from the activation manifest")
    if selection.expected_counts:
        actual = {key: snapshot.report.get(key) for key in selection.expected_counts}
        if actual != dict(selection.expected_counts):
            mismatches = sorted(key for key, value in selection.expected_counts.items() if actual.get(key) != value)
            raise IAPDFirmError("snapshot reconciliation differs from the activation manifest: " + ", ".join(mismatches))
    return {
        "status": "matched_activation_manifest" if selection.activation_id else "observed_latest_manifest",
        "counts_validated": sorted(selection.expected_counts),
    }


def download_feed(definition: FeedDefinition, destination: Path, *, session: requests.Session | None = None,
                  timeout: int = 120) -> str:
    parsed = urlparse(definition.url)
    if parsed.scheme != "https" or parsed.hostname != REPORT_HOST or Path(parsed.path).name != definition.name:
        raise IAPDFirmError("refusing non-official IAPD firm URL")
    client = session or requests.Session()
    response = client.get(definition.url, stream=True, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    final = urlparse(response.url)
    if final.scheme != "https" or final.hostname != REPORT_HOST or Path(final.path).name != definition.name:
        raise IAPDFirmError("IAPD download redirected away from the official report host")
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256()
    received = 0
    temporary: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(dir=destination.parent, prefix=f".{destination.name}.", suffix=".part", delete=False) as output:
            temporary = Path(output.name)
            for chunk in response.iter_content(1024 * 1024):
                if not chunk:
                    continue
                received += len(chunk)
                if received > MAX_COMPRESSED_BYTES:
                    raise IAPDFirmError("compressed IAPD firm feed exceeds size limit")
                digest.update(chunk)
                output.write(chunk)
        validate_gzip(temporary)
        os.replace(temporary, destination)
        return digest.hexdigest()
    except Exception:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
        raise


def validate_gzip(path: Path) -> None:
    expanded = 0
    try:
        with gzip.open(path, "rb") as stream:
            while chunk := stream.read(1024 * 1024):
                expanded += len(chunk)
                if expanded > MAX_UNCOMPRESSED_BYTES:
                    raise IAPDFirmError("expanded IAPD firm feed exceeds size limit")
    except (OSError, EOFError) as exc:
        raise IAPDFirmError("invalid or truncated IAPD gzip feed") from exc
    if expanded == 0:
        raise IAPDFirmError("IAPD firm feed is empty")


def download_official_schemas(destination: Path, *, session: requests.Session | None = None,
                              timeout: int = 60) -> tuple[Path, Path]:
    """Download the published schema archive and extract only the two known XSDs."""
    client = session or requests.Session()
    response = client.get(SCHEMA_ARCHIVE_URL, timeout=timeout, allow_redirects=True)
    response.raise_for_status()
    parsed = urlparse(response.url)
    if parsed.scheme != "https" or parsed.hostname not in {"iard.com", "www.iard.com"}:
        raise IAPDFirmError("firm schema archive redirected away from IARD")
    content = response.content
    if not content or len(content) > 16 * 1024 * 1024:
        raise IAPDFirmError("firm schema archive is empty or exceeds size limit")
    destination = Path(destination)
    destination.mkdir(parents=True, exist_ok=True)
    archive_path = destination / "firm_compilation.zip"
    archive_path.write_bytes(content)
    expected = {
        "IAPDSECBulkFeed.xsd": destination / "IAPDSECBulkFeed.xsd",
        "IAPDStateBulkFeed.xsd": destination / "IAPDStateBulkFeed.xsd",
    }
    try:
        with zipfile.ZipFile(archive_path) as archive:
            if archive.testzip() is not None:
                raise IAPDFirmError("firm schema archive failed CRC validation")
            by_name = {Path(name).name: name for name in archive.namelist()}
            for name, target in expected.items():
                member = by_name.get(name)
                if member is None:
                    raise IAPDFirmError(f"firm schema archive is missing {name}")
                data = archive.read(member)
                if not data or len(data) > 2 * 1024 * 1024:
                    raise IAPDFirmError(f"invalid schema member {name}")
                target.write_bytes(data)
    finally:
        archive_path.unlink(missing_ok=True)
    return expected["IAPDSECBulkFeed.xsd"], expected["IAPDStateBulkFeed.xsd"]


def _decimal(value: str | None) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(value)
    except InvalidOperation:
        return None


def _integer(value: str | None) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _yes(value: str | None) -> bool | None:
    return None if value in (None, "") else value.upper() == "Y"


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _relationship(firm_id: str, relationship_type: str, element: etree._Element | None,
                  *, regulator_code: str | None, snapshot_date: date, dataset_version: str,
                  source_feed: str, source_hash: str) -> FirmRegistrationRelationship:
    return FirmRegistrationRelationship(
        firm_id=firm_id, relationship_type=relationship_type, regulator_code=regulator_code,
        status=element.get("St") if element is not None else None,
        effective_date=_dt(element.get("Dt")) if element is not None else None,
        snapshot_date=datetime.combine(snapshot_date, datetime.min.time()),
        dataset_version=dataset_version, source_feed=source_feed, source_hash=source_hash,
    )


def _firm_facts(element: etree._Element) -> dict[str, Any]:
    info = element.find("Info")
    item1 = element.find("./FormInfo/Part1A/Item1")
    item3a = element.find("./FormInfo/Part1A/Item3A")
    item3c = element.find("./FormInfo/Part1A/Item3C")
    item5a = element.find("./FormInfo/Part1A/Item5A")
    item5b = element.find("./FormInfo/Part1A/Item5B")
    item5d = element.find("./FormInfo/Part1A/Item5D")
    item5f = element.find("./FormInfo/Part1A/Item5F")
    item5g = element.find("./FormInfo/Part1A/Item5G")
    item11 = element.find("./FormInfo/Part1A/Item11")
    filing = element.find("Filing")
    main = element.find("MainAddr")
    websites = [str(node.text).strip() for node in element.findall("./FormInfo/Part1A/Item1/WebAddrs/WebAddr") if node.text and str(node.text).strip()]
    return {
        "firm_id": info.get("FirmCrdNb"), "sec_number": info.get("SECNb"),
        "name": info.get("LegalNm") or info.get("BusNm"), "primary_business_name": info.get("BusNm"),
        "sec_region": info.get("SECRgnCD"), "umbrella_registration": _yes(info.get("UmbrRgstn")),
        "website_address": websites[0] if websites else None,
        "organization_type": item3a.get("OrgFormNm") if item3a is not None else None,
        "organization_state": item3c.get("StateCD") if item3c is not None else None,
        "organization_country": item3c.get("CntryNm") if item3c is not None else None,
        "latest_adv_filing_date": _dt(filing.get("Dt")) if filing is not None else None,
        "form_version": filing.get("FormVrsn") if filing is not None else None,
        "total_aum": _decimal(item5f.get("Q5F2C")) if item5f is not None else None,
        "discretionary_aum": _decimal(item5f.get("Q5F2A")) if item5f is not None else None,
        "non_discretionary_aum": _decimal(item5f.get("Q5F2B")) if item5f is not None else None,
        "discretionary_account_count": _integer(item5f.get("Q5F2D")) if item5f is not None else None,
        "non_discretionary_account_count": _integer(item5f.get("Q5F2E")) if item5f is not None else None,
        "total_account_count": _integer(item5f.get("Q5F2F")) if item5f is not None else None,
        "employee_count": _integer(item5a.get("TtlEmp")) if item5a is not None else None,
        "advisory_employee_count": _integer(item5b.get("Q5B1")) if item5b is not None else None,
        "broker_dealer_rep_count": _integer(item5b.get("Q5B2")) if item5b is not None else None,
        "state_iar_count": _integer(item5b.get("Q5B3")) if item5b is not None else None,
        "individual_client_count": _integer(item5d.get("Q5DA1")) if item5d is not None else None,
        "individual_client_aum": _decimal(item5d.get("Q5DA3")) if item5d is not None else None,
        "hnw_client_count": _integer(item5d.get("Q5DB1")) if item5d is not None else None,
        "hnw_client_aum": _decimal(item5d.get("Q5DB3")) if item5d is not None else None,
        "provides_financial_planning": _yes(item5g.get("Q5G1")) if item5g is not None else None,
        "advises_individuals_or_small_businesses": _yes(item5g.get("Q5G2")) if item5g is not None else None,
        "has_item_11_disclosure": _yes(item11.get("Q11")) if item11 is not None else None,
        "_main_address": dict(main.attrib) if main is not None else {},
        "_item1": dict(item1.attrib) if item1 is not None else {},
    }


def _iter_firms(path: Path, expected_root: str, *, snapshot_date: date,
                schema_path: Path | None = None) -> Iterable[etree._Element]:
    validate_gzip(path)
    if schema_path is not None:
        schema = etree.XMLSchema(etree.parse(str(schema_path)))
        with gzip.open(path, "rb") as stream:
            document = etree.parse(stream)
        if not schema.validate(document):
            raise IAPDFirmError(f"IAPD feed failed XSD validation: {schema.error_log.last_error}")
    with gzip.open(path, "rb") as stream:
        context = etree.iterparse(stream, events=("start", "end"), tag=(expected_root, "Firm"), recover=False, huge_tree=False)
        root_seen = False
        for event, element in context:
            if event == "start" and element.tag == expected_root:
                root_seen = True
                if element.get("GenOn") != snapshot_date.isoformat():
                    raise IAPDFirmError(f"{expected_root} generation date does not match the snapshot")
                continue
            if event == "end" and element.tag == "Firm":
                yield element
                element.clear()
                while element.getprevious() is not None:
                    del element.getparent()[0]
        if not root_seen:
            raise IAPDFirmError(f"expected XML root {expected_root}")


def inspect_snapshot(sec_path: Path, state_path: Path, *, snapshot_date: date,
                     sec_schema: Path | None = None, state_schema: Path | None = None) -> IAPDFirmSnapshot:
    dataset_version = f"iapdfirm{snapshot_date:%Y%m%d}"
    paths = {"sec": Path(sec_path), "state": Path(state_path)}
    hashes = {kind: file_sha256(path) for kind, path in paths.items()}
    records: dict[str, dict[str, Any]] = {}
    relationships: list[FirmRegistrationRelationship] = []
    offices: list[FirmOffice] = []
    feed_ids: dict[str, set[str]] = {"sec": set(), "state": set()}
    feed_counts: Counter[str] = Counter()

    for kind, expected_root, schema in (("sec", "IAPDFirmSECReport", sec_schema), ("state", "IAPDFirmStateReport", state_schema)):
        for element in _iter_firms(paths[kind], expected_root, snapshot_date=snapshot_date, schema_path=schema):
            info = element.find("Info")
            crd = str(info.get("FirmCrdNb") if info is not None else "").strip()
            if not crd or not crd.isdigit():
                raise IAPDFirmError(f"{kind} feed contains a missing or invalid CRD")
            if crd in feed_ids[kind]:
                raise IAPDFirmError(f"{kind} feed contains duplicate CRD {crd}")
            feed_ids[kind].add(crd)
            facts = _firm_facts(element)
            if crd in records:
                before = str(records[crd].get("name") or "").strip().upper()
                after = str(facts.get("name") or "").strip().upper()
                if before != after:
                    raise IAPDFirmError(f"conflicting legal identity for CRD {crd}")
            else:
                records[crd] = facts

            if kind == "sec":
                registration = element.find("Rgstn")
                if registration is None or registration.get("FirmType") not in {"Registered", "ERA"}:
                    raise IAPDFirmError(f"SEC firm {crd} has no recognized registration classification")
                rel_type = "SEC_REGISTRATION" if registration.get("FirmType") == "Registered" else "SEC_ERA"
                relationships.append(_relationship(crd, rel_type, registration, regulator_code="SEC",
                    snapshot_date=snapshot_date, dataset_version=dataset_version, source_feed="SEC", source_hash=hashes[kind]))
                for notice in element.findall("./NoticeFiled/States"):
                    relationships.append(_relationship(crd, "STATE_NOTICE_FILE", notice, regulator_code=notice.get("RgltrCd"),
                        snapshot_date=snapshot_date, dataset_version=dataset_version, source_feed="SEC", source_hash=hashes[kind]))
            else:
                state_regs = element.findall("./StateRgstn/Rgltrs/Rgltr")
                eras = element.findall("./ERA/Rgltrs/Rgltr")
                if not state_regs and not eras:
                    raise IAPDFirmError(f"state firm {crd} has no recognized registration or ERA relationship")
                for registration in state_regs:
                    relationships.append(_relationship(crd, "STATE_REGISTRATION", registration, regulator_code=registration.get("Cd"),
                        snapshot_date=snapshot_date, dataset_version=dataset_version, source_feed="STATE", source_hash=hashes[kind]))
                for era in eras:
                    relationships.append(_relationship(crd, "STATE_ERA", era, regulator_code=era.get("Cd"),
                        snapshot_date=snapshot_date, dataset_version=dataset_version, source_feed="STATE", source_hash=hashes[kind]))

    by_firm: dict[str, list[FirmRegistrationRelationship]] = {}
    for relationship in relationships:
        by_firm.setdefault(relationship.firm_id, []).append(relationship)
    models: list[Firm] = []
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    for crd, facts in records.items():
        rels = by_firm.get(crd, [])
        types = {rel.relationship_type for rel in rels}
        is_sec_registered = "SEC_REGISTRATION" in types
        is_state_registered = "STATE_REGISTRATION" in types
        is_registered = is_sec_registered or is_state_registered
        has_era = bool(types & {"SEC_ERA", "STATE_ERA"})
        review = any(
            (rel.relationship_type == "SEC_REGISTRATION" and rel.status not in _CURRENT_SEC_STATUSES)
            or (rel.relationship_type == "STATE_REGISTRATION" and rel.status not in _CURRENT_STATE_STATUSES)
            for rel in rels
        )
        clean = {key: value for key, value in facts.items() if not key.startswith("_")}
        registration = next((rel for rel in rels if rel.relationship_type == "SEC_REGISTRATION"), None)
        clean.update({
            "dataset_version": dataset_version, "created_timestamp": now,
            "source_dataset": dataset_version,
            "record_hash": hashlib.sha256(json.dumps(clean, sort_keys=True, default=str).encode()).hexdigest(),
            "last_seen_version": dataset_version, "current_status": "active",
            "sec_current_status": registration.status if registration else None,
            "sec_status_effective_date": registration.effective_date if registration else None,
            "canonical_population_source": "IAPD_FIRM_COMPILATION",
            "population_classification": "REGISTERED" if is_registered else "ERA_ONLY",
            "is_registered": is_registered, "is_sec_registered": is_sec_registered,
            "is_state_registered": is_state_registered, "is_era_only": not is_registered and has_era,
            "has_era_relationship": has_era,
            "is_dual_registered": is_sec_registered and is_state_registered,
            "registration_review_required": review,
        })
        if clean.get("individual_client_count") is not None and clean.get("hnw_client_count") is not None:
            clean["individual_hnw_client_count"] = clean["individual_client_count"] + clean["hnw_client_count"]
        if clean.get("individual_client_aum") is not None and clean.get("hnw_client_aum") is not None:
            clean["individual_hnw_client_aum"] = clean["individual_client_aum"] + clean["hnw_client_aum"]
        firm_model = Firm(**clean)
        models.append(firm_model)
        address = facts.get("_main_address") or {}
        if address:
            offices.append(FirmOffice(
                firm_id=crd, office_type=OfficeType.MAIN,
                street_address_1=address.get("Strt1"), street_address_2=address.get("Strt2"),
                city=address.get("City"), state=address.get("State"), country=address.get("Cntry"),
                postal_code=address.get("PostlCd"), telephone=address.get("PhNb"), facsimile=address.get("FaxNb"),
                dataset_version=dataset_version, created_timestamp=now, source_dataset=dataset_version,
                record_hash=firm_model.record_hash, last_seen_version=dataset_version, current_status="active",
            ))

    firms = pd.DataFrame([model.model_dump() for model in models]).sort_values("firm_id").reset_index(drop=True)
    registrations = pd.DataFrame([model.model_dump() for model in relationships]).sort_values(
        ["firm_id", "relationship_type", "regulator_code"], na_position="last"
    ).reset_index(drop=True)
    office_frame = pd.DataFrame([model.model_dump() for model in offices])
    if not office_frame.empty:
        office_frame = office_frame.sort_values(["firm_id", "office_type"]).reset_index(drop=True)
    registered = firms["is_registered"].astype(bool)
    relationship_types = Counter(relationship.relationship_type for relationship in relationships)
    relationship_firms = {
        relationship_type: {relationship.firm_id for relationship in relationships
                            if relationship.relationship_type == relationship_type}
        for relationship_type in ("SEC_REGISTRATION", "SEC_ERA", "STATE_REGISTRATION", "STATE_ERA")
    }
    report = {
        "parser_version": PARSER_VERSION, "dataset_version": dataset_version,
        "snapshot_date": snapshot_date.isoformat(), "source_hashes": hashes,
        "schema_hashes": {
            "sec": file_sha256(sec_schema) if sec_schema is not None else None,
            "state": file_sha256(state_schema) if state_schema is not None else None,
        },
        "sec_feed_rows": len(feed_ids["sec"]),
        "sec_registered_firms": len(relationship_firms["SEC_REGISTRATION"]),
        "sec_era_firms": len(relationship_firms["SEC_ERA"]),
        "state_feed_rows": len(feed_ids["state"]),
        "state_registered_firms": len(relationship_firms["STATE_REGISTRATION"]),
        "state_era_firms": len(relationship_firms["STATE_ERA"]),
        "unique_firms": len(firms), "registered_firms": int(registered.sum()),
        "era_only_firms": int(firms["is_era_only"].astype(bool).sum()),
        "dual_registered_firms": int(firms["is_dual_registered"].astype(bool).sum()),
        "registered_with_era_firms": int((registered & firms["has_era_relationship"].astype(bool)).sum()),
        "cross_feed_overlap": len(feed_ids["sec"] & feed_ids["state"]),
        "relationship_rows": len(relationships), "office_rows": len(offices),
        "relationship_type_counts": dict(sorted(relationship_types.items())),
        "duplicate_crds": 0, "unclassified_firms": 0, "identity_conflicts": 0,
        "relationship_status_counts": dict(sorted(Counter(
            f"{relationship.relationship_type}:{relationship.status or 'MISSING'}"
            for relationship in relationships
        ).items())),
    }
    return IAPDFirmSnapshot(dataset_version, snapshot_date, firms, registrations, office_frame, report)


def inspect_to_report(sec_path: Path, state_path: Path, report_path: Path, *, snapshot_date: date) -> dict[str, Any]:
    snapshot = inspect_snapshot(sec_path, state_path, snapshot_date=snapshot_date)
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = report_path.with_name(f".{report_path.name}.tmp")
    temporary.write_text(json.dumps(snapshot.report, indent=2, sort_keys=True) + "\n")
    os.replace(temporary, report_path)
    return snapshot.report


_SEC_SILVER_RE = re.compile(r"^silver_firms_(ia(\d{2})(\d{2})(\d{4})(?:_\d+)?)$")


def reconcile_sec_silver(snapshot: IAPDFirmSnapshot, duckdb_path: Path) -> dict[str, Any]:
    """Compare against the closest retained SEC Silver roster without merging facts."""
    path = Path(duckdb_path)
    if not path.exists():
        return {"status": "unavailable", "reason": "SEC analytical database does not exist"}
    with duckdb.connect(str(path), read_only=True) as connection:
        candidates: list[tuple[date, str, str]] = []
        for (table,) in connection.execute("SHOW TABLES").fetchall():
            match = _SEC_SILVER_RE.fullmatch(table)
            if match:
                version, month, day, year = match.groups()
                candidates.append((date(int(year), int(month), int(day)), version, table))
        if not candidates:
            return {"status": "unavailable", "reason": "no retained SEC Silver roster exists"}
        sec_date, sec_version, table = max(candidates, key=lambda item: item[0])
        sec_ids = {str(row[0]) for row in connection.execute(f'SELECT firm_id FROM "{table}"').fetchall()}
    iapd_ids = set(snapshot.firms.loc[snapshot.firms["is_sec_registered"].astype(bool), "firm_id"].astype(str))
    report = {
        "status": "matched_date" if sec_date == snapshot.snapshot_date else "date_mismatch_informational",
        "sec_dataset_version": sec_version, "sec_snapshot_date": sec_date.isoformat(),
        "iapd_snapshot_date": snapshot.snapshot_date.isoformat(),
        "snapshot_date_delta_days": (snapshot.snapshot_date - sec_date).days,
        "sec_roster_firms": len(sec_ids), "iapd_sec_registered_firms": len(iapd_ids),
        "matched_crds": len(sec_ids & iapd_ids),
        "sec_roster_missing_from_iapd": len(sec_ids - iapd_ids),
        "iapd_missing_from_sec_roster": len(iapd_ids - sec_ids),
        "sec_roster_missing_from_iapd_sample": sorted(sec_ids - iapd_ids)[:100],
        "iapd_missing_from_sec_roster_sample": sorted(iapd_ids - sec_ids)[:100],
    }
    if sec_date == snapshot.snapshot_date and (sec_ids - iapd_ids or iapd_ids - sec_ids):
        raise IAPDFirmError("equal-date SEC and IAPD firm rosters have unexplained CRD differences")
    return report

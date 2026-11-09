import gzip
import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import pytest

from src.iapd_firms import (
    FeedDefinition, FirmFeedPair, IAPDFirmError, MANIFEST_URL, PARSER_VERSION,
    discover_manifest, download_feed, inspect_snapshot, load_activation_manifest,
    parse_manifest, reconcile_sec_silver, resolve_firm_feed_pair,
    validate_artifact_hashes, validate_snapshot_counts,
)


ACTIVATION_MANIFEST = Path(__file__).resolve().parents[1] / "deploy/iapd-firm-activations/iapdfirm20261107.json"


def _write(path: Path, root: str, firms: str, generated: str = "2026-11-07") -> Path:
    with gzip.open(path, "wb") as stream:
        stream.write(f'<?xml version="1.0" encoding="ISO-8859-1"?><{root} GenOn="{generated}"><Firms>{firms}</Firms></{root}>'.encode("latin-1"))
    return path


def _sec_firm(crd="100", name="EXAMPLE ADVISER", firm_type="Registered", status="APPROVED", notice=True):
    notices = '<States RgltrCd="CA" St="FILED" Dt="2020-01-01"/>' if notice else ""
    return f'''<Firm><Info FirmCrdNb="{crd}" SECNb="801-1" BusNm="{name}" LegalNm="{name}"/>
      <MainAddr State="CA"/><Rgstn FirmType="{firm_type}" St="{status}" Dt="2020-01-01"/>
      <NoticeFiled>{notices}</NoticeFiled><Filing Dt="2026-01-01" FormVrsn="10/2021"/>
      <FormInfo><Part1A><Item1/><Item3A OrgFormNm="LLC"/><Item3C StateCD="CA" CntryNm="United States"/>
      <Item5A TtlEmp="2"/><Item5B Q5B1="1"/><Item5D Q5DA1="2" Q5DA3="25000000" Q5DB1="1" Q5DB3="10000000"/>
      <Item5F Q5F2A="35000000" Q5F2B="0" Q5F2C="35000000" Q5F2D="3" Q5F2E="0" Q5F2F="3"/>
      <Item5G Q5G1="Y" Q5G2="Y"/><Item11 Q11="N"/></Part1A></FormInfo></Firm>'''


def _state_firm(crd="200", name="STATE ADVISER", registered=True, era=False, status="APPROVED"):
    registration = f'<Rgltr Cd="TX" St="{status}" Dt="2020-01-01"/>' if registered else ""
    era_node = '<Rgltr Cd="TX" St="ACTIVE" Dt="2020-01-01"/>' if era else ""
    return f'''<Firm><Info FirmCrdNb="{crd}" BusNm="{name}" LegalNm="{name}"/>
      <MainAddr State="TX"/><StateRgstn><Rgltrs>{registration}</Rgltrs></StateRgstn>
      <ERA><Rgltrs>{era_node}</Rgltrs></ERA><Filing Dt="2026-01-01"/>
      <FormInfo><Part1A><Item1/><Item3A/><Item3C StateCD="TX"/><Item5A/><Item5B/><Item5D/>
      <Item5F/><Item5G/><Item11 Q11="N"/></Part1A></FormInfo></Firm>'''


def test_manifest_requires_one_same_date_sec_and_state_feed():
    payload = {"files": [
        {"name": "IA_FIRM_SEC_Feed_11_07_2026.xml.gz", "date": "11/07/2026"},
        {"name": "IA_FIRM_STATE_Feed_11_07_2026.xml.gz", "date": "11/07/2026"},
        {"name": "IA_INDVL_Feed_11_07_2026.xml.zip", "date": "11/07/2026"},
    ]}
    feeds = parse_manifest(payload)
    assert set(feeds) == {"sec", "state"}
    assert feeds["sec"].snapshot_date == date(2026, 11, 7)
    assert feeds["state"].url.startswith("https://reports.adviserinfo.sec.gov/")

    payload["files"][1]["name"] = "IA_FIRM_STATE_Feed_11_08_2026.xml.gz"
    payload["files"][1]["date"] = "11/08/2026"
    with pytest.raises(IAPDFirmError, match="same snapshot date"):
        parse_manifest(payload)


def test_manifest_accepts_official_octet_stream_and_rejects_redirects():
    payload = {"files": [
        {"name": "IA_FIRM_SEC_Feed_11_07_2026.xml.gz", "date": "11/07/2026"},
        {"name": "IA_FIRM_STATE_Feed_11_07_2026.xml.gz", "date": "11/07/2026"},
    ]}

    class Response:
        headers = {"Content-Type": "binary/octet-stream"}
        content = b"{}"
        url = MANIFEST_URL

        def raise_for_status(self):
            return None

        def json(self):
            return payload

    class Session:
        def get(self, *_args, **_kwargs):
            return Response()

    assert discover_manifest(session=Session())["sec"].snapshot_date == date(2026, 11, 7)
    Response.url = "https://example.test/CompilationReports.manifest.json"
    with pytest.raises(IAPDFirmError, match="redirected away"):
        discover_manifest(session=Session())


def test_resolved_latest_feed_pair_is_discovered_once():
    payload = {"files": [
        {"name": "IA_FIRM_SEC_Feed_11_07_2026.xml.gz", "date": "11/07/2026"},
        {"name": "IA_FIRM_STATE_Feed_11_07_2026.xml.gz", "date": "11/07/2026"},
    ]}

    class Response:
        headers = {"Content-Type": "application/json"}
        content = b"{}"
        url = MANIFEST_URL

        def raise_for_status(self):
            return None

        def json(self):
            return payload

    class Session:
        calls = 0

        def get(self, *_args, **_kwargs):
            self.calls += 1
            return Response()

    session = Session()
    pair = resolve_firm_feed_pair(session=session)
    assert pair.discovery_mode == "latest_manifest"
    assert pair.dataset_version == "iapdfirm20261107"
    assert session.calls == 1


def test_reviewed_activation_manifest_pins_official_sources_hashes_and_counts(tmp_path):
    pair = load_activation_manifest(ACTIVATION_MANIFEST)
    assert pair.discovery_mode == "pinned_activation_manifest"
    assert pair.dataset_version == "iapdfirm20261107"
    assert pair.sec.url.endswith("/IA_FIRM_SEC_Feed_11_07_2026.xml.gz")
    assert pair.expected_counts["registered_firms"] == 33615
    assert pair.expected_counts["state_registered_firms"] == 16587
    assert pair.activation_manifest_hash

    payload = json.loads(ACTIVATION_MANIFEST.read_text())
    payload["feeds"]["sec"]["url"] = "https://attacker.example/IA_FIRM_SEC_Feed_11_07_2026.xml.gz"
    hostile = tmp_path / "hostile.json"
    hostile.write_text(json.dumps(payload))
    with pytest.raises(IAPDFirmError, match="canonical official URL"):
        load_activation_manifest(hostile)


def test_activation_artifact_and_count_mismatches_fail_closed(tmp_path):
    pair = load_activation_manifest(ACTIVATION_MANIFEST)
    with pytest.raises(IAPDFirmError, match="source hashes"):
        validate_artifact_hashes(
            pair,
            source_hashes={"sec": "0" * 64, "state": pair.expected_source_hashes["state"]},
            schema_hashes=pair.expected_schema_hashes,
        )

    sec = _write(tmp_path / "sec.gz", "IAPDFirmSECReport", _sec_firm("100"))
    state = _write(tmp_path / "state.gz", "IAPDFirmStateReport", _state_firm("200"))
    snapshot = inspect_snapshot(sec, state, snapshot_date=date(2026, 11, 7))
    fixture_pair = replace(
        pair,
        expected_counts={key: snapshot.report[key] for key in pair.expected_counts},
        expected_parser_version=PARSER_VERSION,
    )
    assert validate_snapshot_counts(fixture_pair, snapshot)["status"] == "matched_activation_manifest"
    wrong_counts = dict(fixture_pair.expected_counts)
    wrong_counts["registered_firms"] += 1
    with pytest.raises(IAPDFirmError, match="registered_firms"):
        validate_snapshot_counts(replace(fixture_pair, expected_counts=wrong_counts), snapshot)


def test_snapshot_classifies_registration_era_dual_and_notice_separately(tmp_path):
    sec = _write(tmp_path / "sec.gz", "IAPDFirmSECReport", _sec_firm("100") + _sec_firm("300", "SEC ERA", "ERA", "ACTIVE"))
    state = _write(tmp_path / "state.gz", "IAPDFirmStateReport", _state_firm("100", "EXAMPLE ADVISER") + _state_firm("300", "SEC ERA", registered=False, era=True))
    snapshot = inspect_snapshot(sec, state, snapshot_date=date(2026, 11, 7))
    firms = snapshot.firms.set_index("firm_id")
    assert snapshot.dataset_version == "iapdfirm20261107"
    assert len(firms) == 2
    assert bool(firms.loc["100", "is_registered"])
    assert bool(firms.loc["100", "is_dual_registered"])
    assert not bool(firms.loc["100", "is_era_only"])
    assert bool(firms.loc["300", "is_era_only"])
    assert snapshot.report["registered_firms"] == 1
    assert snapshot.report["era_only_firms"] == 1
    relationships = snapshot.registrations
    notice = relationships[relationships.relationship_type == "STATE_NOTICE_FILE"]
    assert len(notice) == 2
    assert snapshot.report["dual_registered_firms"] == 1


def test_unknown_status_requires_review_and_nulls_remain_null(tmp_path):
    sec = _write(tmp_path / "sec.gz", "IAPDFirmSECReport", _sec_firm("100", status="APPROVED-120"))
    state = _write(tmp_path / "state.gz", "IAPDFirmStateReport", _state_firm("200", status="CONDREST"))
    firms = inspect_snapshot(sec, state, snapshot_date=date(2026, 11, 7)).firms.set_index("firm_id")
    assert bool(firms.loc["100", "registration_review_required"])
    assert bool(firms.loc["200", "registration_review_required"])
    assert firms.loc["200", "total_aum"] is None


def test_duplicate_crd_identity_conflict_and_unclassified_fail_closed(tmp_path):
    state = _write(tmp_path / "state.gz", "IAPDFirmStateReport", _state_firm("200"))
    duplicate = _write(tmp_path / "duplicate.gz", "IAPDFirmSECReport", _sec_firm("100") + _sec_firm("100"))
    with pytest.raises(IAPDFirmError, match="duplicate CRD"):
        inspect_snapshot(duplicate, state, snapshot_date=date(2026, 11, 7))

    sec = _write(tmp_path / "sec.gz", "IAPDFirmSECReport", _sec_firm("200", "OTHER NAME"))
    with pytest.raises(IAPDFirmError, match="conflicting legal identity"):
        inspect_snapshot(sec, state, snapshot_date=date(2026, 11, 7))

    unclassified = _write(tmp_path / "unclassified.gz", "IAPDFirmStateReport", _state_firm("200", registered=False, era=False))
    with pytest.raises(IAPDFirmError, match="no recognized"):
        inspect_snapshot(_write(tmp_path / "valid-sec.gz", "IAPDFirmSECReport", _sec_firm()), unclassified, snapshot_date=date(2026, 11, 7))


def test_wrong_root_and_truncated_gzip_are_rejected(tmp_path):
    sec = _write(tmp_path / "sec.gz", "WrongRoot", _sec_firm())
    state = _write(tmp_path / "state.gz", "IAPDFirmStateReport", _state_firm())
    with pytest.raises(IAPDFirmError, match="expected XML root"):
        inspect_snapshot(sec, state, snapshot_date=date(2026, 11, 7))

    broken = tmp_path / "broken.gz"
    broken.write_bytes(b"not gzip")
    with pytest.raises(IAPDFirmError, match="invalid or truncated"):
        inspect_snapshot(broken, state, snapshot_date=date(2026, 11, 7))

    wrong_date = _write(tmp_path / "wrong-date.gz", "IAPDFirmSECReport", _sec_firm(), generated="2026-11-06")
    with pytest.raises(IAPDFirmError, match="generation date"):
        inspect_snapshot(wrong_date, state, snapshot_date=date(2026, 11, 7))


def test_download_rejects_non_official_host_before_request(tmp_path):
    definition = FeedDefinition(
        "sec", "IA_FIRM_SEC_Feed_11_07_2026.xml.gz",
        "https://attacker.example/IA_FIRM_SEC_Feed_11_07_2026.xml.gz",
        date(2026, 11, 7),
    )
    with pytest.raises(IAPDFirmError, match="non-official"):
        download_feed(definition, tmp_path / "feed.gz")


def test_xsd_mismatch_fails_closed(tmp_path):
    sec = _write(tmp_path / "sec.gz", "IAPDFirmSECReport", _sec_firm())
    state = _write(tmp_path / "state.gz", "IAPDFirmStateReport", _state_firm())
    schema = tmp_path / "wrong.xsd"
    schema.write_text('''<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema">
      <xs:element name="IAPDFirmSECReport" type="xs:string"/>
    </xs:schema>''')
    with pytest.raises(IAPDFirmError, match="XSD validation"):
        inspect_snapshot(sec, state, snapshot_date=date(2026, 11, 7), sec_schema=schema)


def test_sec_reconciliation_is_informational_unless_dates_match(tmp_path):
    import duckdb
    import pandas as pd

    sec = _write(tmp_path / "sec.gz", "IAPDFirmSECReport", _sec_firm("100"))
    state = _write(tmp_path / "state.gz", "IAPDFirmStateReport", _state_firm("200"))
    snapshot = inspect_snapshot(sec, state, snapshot_date=date(2026, 11, 7))
    database = tmp_path / "analytics.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.register("frame", pd.DataFrame({"firm_id": ["100", "999"]}))
        connection.execute('create table silver_firms_ia11012026 as select * from frame')
    report = reconcile_sec_silver(snapshot, database)
    assert report["status"] == "date_mismatch_informational"
    assert report["matched_crds"] == 1
    assert report["sec_roster_missing_from_iapd"] == 1

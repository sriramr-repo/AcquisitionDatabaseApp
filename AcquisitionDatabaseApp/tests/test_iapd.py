from __future__ import annotations

import io
import zipfile
from datetime import date
from pathlib import Path

import pytest

from src import iapd


SAMPLE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<IAPD>
  <Indvl>
    <Info><firstName>Jane</firstName><middleName>Q</middleName><lastName>Advisor</lastName><suffix>CFP</suffix><indvlPK>12345</indvlPK><activeAGRegistration>Y</activeAGRegistration><compositeLink>/individual/12345</compositeLink></Info>
    <OthrNms><OthrNm><firstName>J</firstName><lastName>Advisor</lastName></OthrNm></OthrNms>
    <CrntEmps><CrntEmp><orgPK>98765</orgPK><orgName>Example Advisory LLC</orgName><address1>1 Main St</address1><city>Boston</city><state>MA</state><zipCode>02110</zipCode><country>US</country>
      <CrntRgstns><CrntRgstn><regAuthority>Massachusetts</regAuthority><regCategory>IA Representative</regCategory><regStatus>Approved</regStatus><statusDate>2026-08-04</statusDate></CrntRgstn></CrntRgstns>
      <BrnchOfcs><BrnchOfc><branchName>Boston Branch</branchName><address1>2 Branch Rd</address1><city>Boston</city><state>MA</state></BrnchOfc></BrnchOfcs>
    </CrntEmp></CrntEmps>
    <PrevRgstns><PrevRgstn><orgPK>11111</orgPK><orgName>Prior Advisory</orgName><regAuthority>New York</regAuthority><regStatus>Terminated</regStatus><beginDate>2019-01-01</beginDate><endDate>2023-01-01</endDate></PrevRgstn></PrevRgstns>
    <EmpHss><EmpHs><orgName>Historic Employer</orgName><city>New York</city><state>NY</state><fromDate>2010-01-01</fromDate><toDate>2019-01-01</toDate></EmpHs></EmpHss>
    <OthrBuss><OthrBus><description>Insurance agent</description></OthrBus></OthrBuss>
    <DRPs><DRP><regAction>N</regAction><criminal>Y</criminal><bankrupt>N</bankrupt><civilJudgment>N</civilJudgment><bond>N</bond><judgment>N</judgment><investigation>Y</investigation><customerComplaint>N</customerComplaint><termination>N</termination></DRP></DRPs>
  </Indvl>
  <Indvl><Info><firstName>Missing</firstName><indvlPK>54321</indvlPK></Info></Indvl>
</IAPD>"""

SEC_ATTRIBUTE_XML = b"""<?xml version="1.0" encoding="UTF-8"?>
<IAPDIndividualReport GenOn="2026-08-20"><Indvls><Indvl>
  <Info firstNm="John" midNm="Q" lastNm="Advisor" indvlPK="45678" actvAGReg="Y" link="/individual/45678" />
  <CrntEmps><CrntEmp orgPK="98765" orgNm="Example Advisory LLC" str1="1 Main St" city="Boston" st="MA" postlCd="02110" cntry="USA">
    <CrntRgstns><CrntRgstn regAuth="MA" regCat="RA" st="APPROVED" stDt="2026-08-01" /></CrntRgstns>
  </CrntEmp></CrntEmps>
  <EmpHss><EmpHs orgNm="Prior Advisory" city="New York" st="NY" fromDt="2018-01-01" toDt="2022-01-01" /></EmpHss>
  <OthrBuss><OthrBus desc="Insurance agent" /></OthrBuss>
  <DRPs><DRP hasRegAction="N" hasCriminal="Y" /></DRPs>
</Indvl></Indvls></IAPDIndividualReport>"""


def test_build_iapd_feed_url_uses_month_day_year_pattern():
    assert iapd.build_iapd_feed_url(date(2026, 8, 4)).endswith("IA_INDVL_Feed_08_04_2026.xml.zip")


def test_parse_iapd_xml_normalizes_person_and_nested_collections(tmp_path):
    xml_path = tmp_path / "iapd.xml"
    xml_path.write_bytes(SAMPLE_XML)
    people = list(iapd.parse_iapd_xml(xml_path))
    assert len(people) == 2
    person = people[0]
    assert person["individual_crd"] == "12345"
    assert person["full_name"] == "Jane Q Advisor CFP"
    assert person["active_ag_registration"] is True
    assert person["aliases"][0]["alias_name"] == "J Advisor"
    employment = person["current_employments"][0]
    assert employment["employer_firm_crd"] == "98765"
    assert employment["city"] == "Boston"
    assert employment["registrations"][0]["status"] == "Approved"
    assert employment["branches"][0]["branch_name"] == "Boston Branch"
    assert person["previous_registrations"][0]["begin_date"] == "2019-01-01"
    assert person["employment_history"][0]["organization_name"] == "Historic Employer"
    assert person["other_businesses"][0]["description"] == "Insurance agent"
    assert person["disclosures"][0]["criminal"] is True
    assert person["disclosures"][0]["investigation"] is True
    assert people[1]["current_employments"] == []
    assert people[1]["disclosures"] == []


def test_parse_iapd_xml_accepts_the_sec_attribute_feed_shape(tmp_path):
    xml_path = tmp_path / "sec-feed.xml"
    xml_path.write_bytes(SEC_ATTRIBUTE_XML)
    person = list(iapd.parse_iapd_xml(xml_path))[0]
    assert person["full_name"] == "John Q Advisor"
    assert person["current_employments"][0]["employer_firm_crd"] == "98765"
    assert person["current_employments"][0]["registrations"][0]["status"] == "APPROVED"
    assert person["employment_history"][0]["organization_name"] == "Prior Advisory"
    assert person["other_businesses"][0]["description"] == "Insurance agent"
    assert person["disclosures"][0]["criminal"] is True


def test_scope_inspection_counts_only_matching_current_employments(tmp_path):
    zip_path = tmp_path / "feed.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("feed.xml", SAMPLE_XML)
    summary = iapd.inspect_iapd_scope(zip_path, {"98765"})
    assert summary["individuals"] == 1
    assert summary["current_employments"] == 1
    assert summary["current_registrations"] == 1


def test_extract_iapd_xml_and_validate_zip(tmp_path):
    zip_path = tmp_path / "feed.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("IA_INDVL_Feed.xml", SAMPLE_XML)
    extracted = iapd.extract_iapd_xml(zip_path)
    assert extracted.read_bytes() == SAMPLE_XML


def test_multi_part_compilation_zip_streams_all_xml_members(tmp_path):
    zip_path = tmp_path / "multipart.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("part_1.xml", SAMPLE_XML)
        archive.writestr("part_2.xml", SAMPLE_XML)
    assert len(iapd._validate_zip(zip_path)) == 2
    assert len(list(iapd.parse_iapd_zip(zip_path))) == 4
    with pytest.raises(iapd.IAPDFeedUnavailable, match="streaming"):
        iapd.extract_iapd_xml(zip_path)


def test_extract_rejects_empty_or_non_xml_zip_members(tmp_path):
    zip_path = tmp_path / "bad-feed.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("readme.txt", "not an IAPD feed")
    with pytest.raises(iapd.IAPDFeedUnavailable):
        iapd.extract_iapd_xml(zip_path)


def test_malformed_xml_is_rejected_before_import(tmp_path):
    xml_path = tmp_path / "broken.xml"
    xml_path.write_text("<IAPD><Indvl>")
    with pytest.raises(iapd.IAPDFeedUnavailable):
        iapd.validate_iapd_xml(xml_path)


def test_monthly_job_skips_outside_scheduled_day():
    result = iapd.run_iapd_monthly(database_url="postgresql://unused", run_date=date(2026, 8, 5))
    assert result == {"status": "skipped", "reason": "not_scheduled_day", "snapshot_date": "2026-08-05"}


def test_monthly_job_reports_targeted_fallback_when_feed_is_unavailable(monkeypatch):
    def unavailable(*args, **kwargs):
        raise iapd.IAPDFeedUnavailable("HTTP 403")
    monkeypatch.setattr(iapd, "download_iapd_feed", unavailable)
    result = iapd.run_iapd_monthly(database_url="postgresql://unused", run_date=date(2026, 8, 4))
    assert result["status"] == "fallback_required"
    assert result["reason"] == "monthly_feed_unavailable"


def test_download_rejects_non_zip_response(tmp_path, monkeypatch):
    class Response:
        status_code = 200
        def raise_for_status(self): pass
        def iter_content(self, chunk_size): yield b"<html>not a zip</html>"
    class Session:
        def get(self, *args, **kwargs): return Response()
    monkeypatch.setattr(iapd.settings, "BASE_DIR", tmp_path)
    with pytest.raises(iapd.IAPDFeedUnavailable):
        iapd.download_iapd_feed(date(2026, 8, 4), session=Session(), retries=1)


def test_download_retries_with_browser_style_headers(tmp_path, monkeypatch):
    class Response:
        def __init__(self, status_code=403, body=b""):
            self.status_code = status_code
            self._body = body
        def raise_for_status(self):
            if self.status_code >= 400 and self.status_code != 403:
                raise RuntimeError("unexpected")
        def iter_content(self, chunk_size):
            yield self._body
    class Session:
        def __init__(self):
            self.calls = []
        def get(self, url, headers=None, timeout=None, stream=None):
            self.calls.append(headers.get("Referer"))
            if len(self.calls) < 3:
                return Response(403)
            body = io.BytesIO()
            with zipfile.ZipFile(body, "w") as archive:
                archive.writestr("feed.xml", SAMPLE_XML)
            return Response(200, body.getvalue())
    monkeypatch.setattr(iapd.settings, "BASE_DIR", tmp_path)
    session = Session()
    destination, url, checksum = iapd.download_iapd_feed(date(2026, 8, 4), session=session, retries=1)
    assert destination.exists()
    assert url.endswith("IA_INDVL_Feed_08_04_2026.xml.zip")
    assert checksum
    assert len(session.calls) == 3


def test_duplicate_snapshot_protection_returns_before_parsing(tmp_path, monkeypatch):
    zip_path = tmp_path / "feed.zip"
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.writestr("feed.xml", SAMPLE_XML)
    xml_path = iapd.extract_iapd_xml(zip_path)
    class Cursor:
        def fetchone(self): return ("existing-snapshot", "SUCCESS")
    class Connection:
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def execute(self, *args, **kwargs): return Cursor()
    class Psycopg:
        @staticmethod
        def connect(*args, **kwargs): return Connection()
    monkeypatch.setitem(__import__("sys").modules, "psycopg", Psycopg)
    result = iapd.import_iapd_snapshot(xml_path, snapshot_date=date(2026, 8, 4), source_url="https://example.test/feed.zip", source_zip=zip_path, database_url="postgresql://unused")
    assert result == {"status": "skipped", "snapshot_id": "existing-snapshot", "reason": "duplicate_snapshot"}


def test_manual_import_from_paths_requires_zip(tmp_path):
    xml_path = tmp_path / "feed.xml"
    xml_path.write_text(SAMPLE_XML.decode("utf-8"))
    with pytest.raises(FileNotFoundError):
        iapd.import_iapd_from_paths(
            database_url="postgresql://unused",
            snapshot_date=date(2026, 8, 4),
            source_url="https://example.test/feed.zip",
            xml_path=xml_path,
        )

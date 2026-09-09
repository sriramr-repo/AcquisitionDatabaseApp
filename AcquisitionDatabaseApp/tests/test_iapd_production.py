from __future__ import annotations

import io
import json
import sys
import zipfile
from datetime import date, datetime, timedelta, timezone

import duckdb
import pytest

from src import iapd, iapd_batch, iapd_recovery


def _zip(path, records=2):
    people = "".join(
        f'<Indvl><Info indvlPK="{index}" firstNm="Jos\u00e9" lastNm="O\'Neil Jr." />'
        f'<CrntEmps><CrntEmp orgPK="{100 + index}" orgNm="Firm {index}"><CrntRgstns>'
        f'<CrntRgstn regAuth="MA" regCat="RA" st="APPROVED_RES" stDt="2026-09-01" />'
        '</CrntRgstns></CrntEmp></CrntEmps></Indvl>' for index in range(1, records + 1)
    )
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("readme.txt", "official compilation")
        archive.writestr("nested/feed.xml", f'<IAPDIndividualReport><Indvls>{people}</Indvls></IAPDIndividualReport>')
    return path


def test_feed_health_accepts_namespaces_unicode_and_unusual_status(tmp_path):
    source = _zip(tmp_path / "feed.zip")
    health = iapd_recovery.inspect_feed_health(source, minimum_records=2)
    assert health["unique_representatives"] == 2
    assert health["current_registrations"] == 2
    people = list(iapd.parse_iapd_zip(source))
    assert people[0]["full_name"] == "Jos\u00e9 O'Neil Jr."
    assert people[0]["current_employments"][0]["registrations"][0]["status"] == "APPROVED_RES"


def test_feed_health_rejects_tiny_and_duplicate_heavy_candidates(tmp_path):
    source = _zip(tmp_path / "tiny.zip", records=1)
    with pytest.raises(iapd.IAPDFeedUnavailable, match="implausibly small"):
        iapd_recovery.inspect_feed_health(source, minimum_records=2)
    duplicate = tmp_path / "duplicates.zip"
    xml = b'<IAPD><Indvl><Info indvlPK="1"/><CrntEmps><CrntEmp orgPK="2"/></CrntEmps></Indvl><Indvl><Info indvlPK="1"/><CrntEmps><CrntEmp orgPK="3"/></CrntEmps></Indvl></IAPD>'
    with zipfile.ZipFile(duplicate, "w") as archive:
        archive.writestr("feed.xml", xml)
    with pytest.raises(iapd.IAPDFeedUnavailable, match="duplicate ratio"):
        iapd_recovery.inspect_feed_health(duplicate, minimum_records=1)


def test_monthly_recovery_uses_latest_official_fallback_and_records_attempts(tmp_path, monkeypatch):
    source = _zip(tmp_path / "feed.zip")
    calls = []
    def download(value, session=None):
        calls.append(value)
        if value == date(2026, 9, 4):
            raise iapd.IAPDFeedUnavailable("HTTP 403")
        return source, iapd.build_iapd_feed_url(value), "hash"
    monkeypatch.setattr(iapd_recovery, "download_iapd_feed", download)
    monkeypatch.setattr(iapd_recovery, "discover_compilation", lambda session=None: [date(2026, 9, 6)])
    monkeypatch.setattr(iapd_recovery, "_previous_local_count", lambda: None)
    monkeypatch.setattr(iapd_recovery, "repair_iapd_firm_summaries", lambda **kwargs: {"firm_count": 10})
    recorded = []
    monkeypatch.setattr(iapd_recovery, "_record_feed_run", lambda database_url, report: recorded.append(dict(report)))
    result = iapd_recovery.monthly_refresh_with_recovery(
        database_url="unused", run_date=date(2026, 9, 4), minimum_records=2,
    )
    assert result["status"] == "fallback_success"
    assert result["snapshot_date"] == "2026-09-06"
    assert [row["status"] for row in result["attempts"]] == ["failed", "retrieved"]
    assert recorded[-1]["status"] == "fallback_success"
    assert recorded[0]["status"] == "running"


def test_download_retries_rate_limit_and_honors_valid_zip(tmp_path, monkeypatch):
    body = io.BytesIO()
    with zipfile.ZipFile(body, "w") as archive:
        archive.writestr("feed.xml", '<IAPD><Indvl><Info indvlPK="1"/></Indvl></IAPD>')
    class Response:
        def __init__(self, status, payload=b""):
            self.status_code, self.payload, self.headers = status, payload, {"Retry-After":"0"}
        def raise_for_status(self):
            if self.status_code >= 400: raise RuntimeError(str(self.status_code))
        def iter_content(self, chunk_size): yield self.payload
    class Session:
        def __init__(self): self.calls = 0
        def get(self, *args, **kwargs):
            self.calls += 1
            return Response(429) if self.calls <= 3 else Response(200, body.getvalue())
    monkeypatch.setattr(iapd.settings, "BASE_DIR", tmp_path)
    session = Session()
    result = iapd.download_iapd_feed(date(2026, 9, 4), session=session, retries=2)
    assert result[0].is_file()
    assert session.calls == 4


def test_local_monthly_rows_keep_zero_disclosures_and_multiple_employers(tmp_path):
    database = tmp_path / "iapd.duckdb"
    with duckdb.connect(str(database)) as connection:
        connection.execute("create table iapd_snapshot(snapshot_id varchar,snapshot_date date,source_url varchar)")
        connection.execute("insert into iapd_snapshot values ('s','2026-09-06','https://adviserinfo.sec.gov/')")
        connection.execute("create table iapd_people(snapshot_id varchar,individual_crd varchar,full_name varchar,payload_json json)")
        connection.execute("insert into iapd_people values ('s','1','Jane',?)", [json.dumps({"disclosures":[]})])
        connection.execute("create table iapd_current_links(snapshot_id varchar,firm_id varchar,individual_crd varchar,employment_id varchar,employment_json json)")
        for firm in ("2","3"):
            connection.execute("insert into iapd_current_links values ('s',?,'1',?,?)", [firm,firm,json.dumps({"employer_firm_crd":firm,"employer_name":f"Firm {firm}","registrations":[]})])
    rows = iapd_batch._monthly_rows_from_local(database, "1")
    assert len(rows) == 2
    assert {row["employer_firm_crd"] for row in rows} == {"2","3"}
    assert all(row["disclosure_summary"] == "0 disclosures reported" for row in rows)


@pytest.mark.parametrize("limit,workers,days", [(0,1,30),(1,0,30),(1,1,0),(1001,1,30),(1,9,30)])
def test_live_batch_bounds_are_enforced_before_database_access(limit,workers,days):
    with pytest.raises(ValueError):
        iapd_batch.run_live_batch(database_url="unused",local_database=__import__('pathlib').Path('missing'),limit=limit,workers=workers,freshness_days=days)


def test_failure_classification_is_safe_and_reviewable():
    assert iapd_batch._safe_reason(iapd.IAPDFeedUnavailable("HTTP 429")) == "TRANSIENT_SOURCE_FAILURE"
    assert iapd_batch._safe_reason(ValueError("bad input")) == "INVALID_REQUEST"
    assert iapd_batch._safe_reason(RuntimeError("Live page CRD 9 does not match requested CRD 1")) == "CRD_MISMATCH"


def test_live_queue_is_bounded_and_skips_fresh_or_exhausted_records():
    now = datetime.now(timezone.utc)
    candidates = [(str(value), value) for value in range(1, 8)]
    existing = {
        "1": ("SUCCESS", now, 1, {"reconciliation_version": iapd_batch.VERSION}),
        "2": ("UNCHANGED", now, 1, {"reconciliation_version": iapd_batch.VERSION}),
        "3": ("FAILED", None, 3, {}),
        "4": ("SUCCESS", now - timedelta(days=90), 1, {"reconciliation_version": iapd_batch.VERSION}),
    }
    selected, fresh_skipped = iapd_batch._select_candidates_for_enqueue(
        candidates,
        existing,
        fresh_after=now - timedelta(days=30),
        enqueue_limit=2,
        max_attempts=3,
    )
    assert selected == [("4", 4), ("5", 5)]
    assert fresh_skipped == 2

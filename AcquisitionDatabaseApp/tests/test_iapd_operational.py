from datetime import datetime, timezone
from pathlib import Path
import duckdb
import pytest
from src.iapd_batch import candidate_rank, run_live_batch, _select_candidates_for_enqueue
from src.iapd_live import retry_after_seconds, capture_iapd_live_page, IAPDLiveUnavailable
from src.iapd_local import previous_distinct_snapshot


def test_business_priority_before_aum_then_gaps_disclosures_and_age():
    now = datetime.now(timezone.utc)
    def rank(priority="PRIORITY_A", aum=1, fields=None, disclosure=False, date=now, crd="1"):
        return candidate_rank(priority, aum, fields or {}, disclosure, date, crd)
    assert rank(aum=300e6) < rank(priority="PRIORITY_B")
    assert rank() < rank(aum=None)
    assert rank() < rank(fields={"phone":"1"})
    assert rank(disclosure=True) < rank()
    assert rank(date=None) < rank()
    assert rank(crd="2") < rank(crd="10")


def test_resume_must_identify_batch_before_access():
    with pytest.raises(ValueError, match="explicit batch_id"):
        run_live_batch(database_url="unused", local_database=Path("missing"), resume=True)


def test_inflight_jobs_are_not_reassigned():
    now = datetime.now(timezone.utc)
    existing = {str(i):(status,None,1,{}) for i,status in enumerate(["RUNNING","QUEUED","RETRY_PENDING"])}
    selected, _ = _select_candidates_for_enqueue([(str(i),i) for i in range(4)],existing,fresh_after=now,enqueue_limit=50,max_attempts=3)
    assert selected == [("3",3)]


def test_single_network_attempt_and_retry_after():
    class Response:
        status_code=429
        headers={"Retry-After":"120"}
    class Session:
        calls=0
        def post(self,*args,**kwargs):
            self.calls += 1
            return Response()
    session=Session()
    with pytest.raises(IAPDLiveUnavailable) as raised:
        capture_iapd_live_page(individual_crd="1",database_url="unused",api_key="fixture",session=session,attempts=1)
    assert session.calls == 1
    assert raised.value.retry_after == 120
    assert retry_after_seconds("garbage") == 0


def test_selects_nearest_distinct_snapshot(tmp_path):
    for name, identity, day in [("current","c","2026-09-08"),("same","c","2026-09-08"),("old","a","2026-07-01"),("prior","b","2026-08-20")]:
        directory=tmp_path/name
        directory.mkdir()
        with duckdb.connect(str(directory/"iapd.duckdb")) as c:
            c.execute("create table iapd_snapshot(snapshot_id varchar,snapshot_date date)")
            c.execute("insert into iapd_snapshot values (?,?)",[identity,day])
    assert previous_distinct_snapshot(tmp_path/"current"/"iapd.duckdb") == tmp_path/"prior"/"iapd.duckdb"

import copy
import pytest
from src.iapd_review import resolved_fields


def fixture():
    record = {"effective_fields":{"registration_date":"2026-08-12","current_employers":[{"crd":"1"},{"crd":"2"}]},"conflicts":{"registration_date":{"monthly":"2026-08-12","live":"2025-03-28"}},"snapshot_id":"s","capture_id":"c"}
    review = {"review_id":"r","individual_crd":"123","reason_code":"REGISTRATION_DATE","details":copy.deepcopy(record["conflicts"]["registration_date"])}
    return record, review


def resolve(record, review, resolution="monthly_preferred"):
    return resolved_fields(record,review,resolution=resolution,reviewer="Operator",rationale="Different date semantics",evidence_url="https://adviserinfo.sec.gov/individual/summary/123")


def test_resolution_preserves_original_evidence():
    record,review=fixture()
    before=copy.deepcopy(record)
    effective, conflicts, freshness, decision=resolve(record,review)
    assert record == before
    assert effective["registration_date"] == "2026-08-12"
    assert conflicts == {} and freshness == "monthly_confirmed"
    assert decision["original_details"]["live"] == "2025-03-28"


def test_live_preference_retains_provenance():
    record,review=fixture()
    effective,*_=resolve(record,review,"live_preferred")
    assert effective["registration_date"] == "2025-03-28"
    assert effective["provenance"]["registration_date"]["source_id"] == "c"


def test_multiple_employers_are_not_collapsed():
    record,review=fixture()
    review["reason_code"]="MULTIPLE_CURRENT_EMPLOYERS"
    effective,conflicts,*_=resolve(record,review)
    assert len(effective["current_employers"]) == 2
    assert "registration_date" in conflicts
    with pytest.raises(ValueError): resolve(record,review,"resolved_same_entity")


def test_missing_conflict_cannot_be_resolved():
    record,review=fixture()
    record["conflicts"]={}
    with pytest.raises(ValueError): resolve(record,review)


def test_review_transaction_postgres(monkeypatch):
    import os
    import json
    from contextlib import nullcontext
    from src.iapd_review import resolve_review
    url=os.getenv("SCM_TEST_DATABASE_URL")
    if not url: pytest.skip("SCM_TEST_DATABASE_URL required; only temporary tables are modified")
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(url, row_factory=dict_row) as connection:
        with connection.transaction(force_rollback=True):
            for table in ("iapd_manual_review_queue","iapd_individual_reconciliations"):
                connection.execute(f"CREATE TEMP TABLE {table} (LIKE public.{table} INCLUDING ALL) ON COMMIT DROP")
            record,review=fixture()
            connection.execute("INSERT INTO iapd_individual_reconciliations (reconciliation_id,individual_crd,snapshot_id,capture_id,effective_fields,freshness,confidence,conflicts,created_at) VALUES ('base','123','s','c',%s,'conflict','HIGH',%s,now()-interval '1 minute')", (json.dumps(record['effective_fields']),json.dumps(record['conflicts'])))
            connection.execute("INSERT INTO iapd_manual_review_queue (review_id,individual_crd,reason_code,status,monthly_snapshot_id,live_capture_id,details) VALUES ('r','123','REGISTRATION_DATE','OPEN','s','c',%s)",(json.dumps(review['details']),))
            monkeypatch.setattr(psycopg,"connect",lambda *a,**kw:nullcontext(connection))
            args=dict(database_url=url,review_id='r',resolution='monthly_preferred',reviewer='fixture',rationale='Different semantics',evidence_url='https://adviserinfo.sec.gov/individual/summary/123')
            assert resolve_review(**args)['status']=='resolved'
            assert resolve_review(**args)['status']=='already_reviewed'
            assert connection.execute("SELECT count(*) n FROM iapd_individual_reconciliations").fetchone()['n']==2
            assert connection.execute("SELECT status FROM iapd_manual_review_queue").fetchone()['status']=='RESOLVED'

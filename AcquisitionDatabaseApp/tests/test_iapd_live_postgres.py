"""Opt-in PostgreSQL smoke test; source tables are shadowed by temporary tables."""
import os
from contextlib import nullcontext
import pytest
from src import iapd_live


def test_capture_reconcile_and_history_postgres(monkeypatch):
    url=os.getenv('SCM_TEST_DATABASE_URL')
    if not url:
        pytest.skip('SCM_TEST_DATABASE_URL required')
    import psycopg
    from psycopg.rows import dict_row
    with psycopg.connect(url,connect_timeout=10,row_factory=dict_row) as conn:
        with conn.transaction(force_rollback=True):
            for table in ['iapd_individual_snapshots','iapd_individual_current_employments','iapd_individual_current_registrations','iapd_live_captures','iapd_individual_live_enrichments','iapd_individual_reconciliations']:
                conn.execute(f'CREATE TEMP TABLE {table} (LIKE public.{table} INCLUDING ALL) ON COMMIT DROP')
            monkeypatch.setattr(psycopg,'connect',lambda *a,**kw:nullcontext(conn))
            class Response:
                status_code=200
                def raise_for_status(self): pass
                def json(self):return {'data':{'markdown':'Individual CRD: 123\nName: Test Person\nCurrent Employer CRD: 42\nCurrent Employer: Test Firm\nPhone: 0'}}
            class Session:
                def post(self,*a,**kw):return Response()
            for _ in range(2):
                result=iapd_live.capture_iapd_live_page(individual_crd='123',database_url=url,api_key='fixture',session=Session())
                assert result['reconciliation']['effective_fields']['phone']=='0'
            assert conn.execute('select count(*) n from iapd_live_captures').fetchone()['n']==2
            assert conn.execute('select count(*) n from iapd_individual_reconciliations').fetchone()['n']==2

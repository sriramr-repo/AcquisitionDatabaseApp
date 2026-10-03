"""Optional PostgreSQL integration; all fixture tables are connection-local TEMP tables."""
import os
from contextlib import nullcontext
from types import SimpleNamespace

import pytest

from src import dashboard_publisher as publisher


@pytest.fixture
def office_db(monkeypatch, tmp_path):
    url = os.environ.get('SCM_TEST_DATABASE_URL')
    if not url:
        pytest.skip('SCM_TEST_DATABASE_URL required for isolated PostgreSQL tests')
    import psycopg
    with psycopg.connect(url, autocommit=True) as conn:
        with conn.transaction(force_rollback=True):
            conn.execute('CREATE TEMP TABLE dataset_versions (dataset_version text, published_at timestamptz)')
            conn.execute("INSERT INTO dataset_versions VALUES ('fixture',now())")
            conn.execute('CREATE TEMP TABLE firm_facts (firm_id text, dataset_version text, updated_at timestamptz,' + ','.join(f'{k} text' for k in publisher.OFFICE_FIELDS) + ')')
            conn.execute("INSERT INTO firm_facts(firm_id,dataset_version) VALUES ('1','fixture')")
            conn.execute('CREATE TEMP TABLE outreach_targets (status text)')
            conn.execute("INSERT INTO outreach_targets VALUES ('DO_NOT_CONTACT')")
            monkeypatch.setattr(psycopg, 'connect', lambda _: nullcontext(conn))
            monkeypatch.setattr(publisher, 'settings', SimpleNamespace(RAW_DIR=tmp_path, DUCKDB_FILE=tmp_path/'unused'))
            monkeypatch.setattr(publisher, '_main_offices', lambda *args: {'1':{'main_office_phone':'012345','main_office_postal_code':'02110'}})
            yield conn, url


def test_office_publish_is_idempotent_and_preserves_workflow(office_db):
    conn, url = office_db
    assert publisher.publish_office_contacts('fixture', url)['updated'] == 1
    assert publisher.publish_office_contacts('fixture', url)['updated'] == 0
    assert conn.execute('SELECT main_office_phone,main_office_postal_code,main_office_city FROM firm_facts').fetchone() == ('012345','02110',None)
    assert conn.execute('SELECT status FROM outreach_targets').fetchone() == ('DO_NOT_CONTACT',)


def test_office_publish_rejects_mismatched_universe_without_writes(office_db):
    conn, url = office_db
    conn.execute("INSERT INTO firm_facts(firm_id,dataset_version) VALUES ('2','fixture')")
    with pytest.raises(ValueError, match='exactly match'):
        publisher.publish_office_contacts('fixture', url)
    assert conn.execute('SELECT count(*) FROM firm_facts WHERE main_office_phone IS NOT NULL').fetchone()[0] == 0


def test_office_publish_rejects_old_dataset(office_db):
    conn, url = office_db
    with pytest.raises(ValueError, match='active'):
        publisher.publish_office_contacts('old', url)
    assert conn.execute('SELECT count(*) FROM firm_facts WHERE main_office_phone IS NOT NULL').fetchone()[0] == 0

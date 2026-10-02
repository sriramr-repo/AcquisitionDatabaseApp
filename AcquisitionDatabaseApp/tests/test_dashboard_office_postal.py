import duckdb
import csv
import io
import zipfile
import pytest

from src.dashboard_publisher import _main_offices
from src.dashboard_publisher import _bronze_offices, OFFICE_FIELDS


def test_publisher_reads_full_main_address_without_changing_silver(tmp_path):
    path = str(tmp_path / "fixture.duckdb")
    with duckdb.connect(path) as conn:
        conn.execute("""CREATE TABLE silver_firm_offices_fixture (
            firm_id VARCHAR, street_address_1 VARCHAR, street_address_2 VARCHAR,
            city VARCHAR, state VARCHAR, country VARCHAR, telephone VARCHAR,
            postal_code VARCHAR, office_type VARCHAR)""")
        conn.execute("""INSERT INTO silver_firm_offices_fixture VALUES
            ('1','1 Main','Suite 2','Boston','MA','United States','617-555-0100','02110','MAIN'),
            ('2',NULL,NULL,NULL,NULL,NULL,NULL,NULL,'MAIN'),
            ('1','Branch',NULL,'Other','MA','United States',NULL,'00000','BRANCH')""")
    before = __import__('hashlib').sha256(open(path, 'rb').read()).hexdigest()
    offices = _main_offices(path, 'fixture')
    assert offices['1']['main_office_postal_code'] == '02110'
    assert offices['1']['main_office_street_address_2'] == 'Suite 2'
    assert offices['1']['main_office_phone'] == '617-555-0100'
    assert offices['2']['main_office_postal_code'] is None
    assert __import__('hashlib').sha256(open(path, 'rb').read()).hexdigest() == before


def test_missing_silver_office_table_uses_exact_bronze_dataset(tmp_path):
    path = tmp_path / 'fixture.duckdb'
    with duckdb.connect(str(path)):
        pass
    source = tmp_path / 'fixture.zip'
    content = io.StringIO()
    writer = csv.DictWriter(content, fieldnames=['Organization CRD#', *OFFICE_FIELDS.values()])
    writer.writeheader()
    writer.writerow({'Organization CRD#':'123','Main Office Street Address 1':' 1 Main ', 'Main Office Postal Code':'02110', 'Main Office Telephone Number':'+1 (617) 555-0100'})
    with zipfile.ZipFile(source, 'w') as archive:
        archive.writestr('roster.csv', content.getvalue())
    facts = _main_offices(str(path), 'fixture', source)
    assert facts['123']['main_office_street_address_1'] == '1 Main'
    assert facts['123']['main_office_postal_code'] == '02110'
    assert facts['123']['main_office_city'] is None
    with pytest.raises(ValueError, match='match'):
        _bronze_offices(source, 'other')
    with zipfile.ZipFile(source, 'w') as archive:
        archive.writestr('roster.csv', content.getvalue() + content.getvalue().splitlines()[1] + '\n')
    with pytest.raises(ValueError, match='duplicate'):
        _bronze_offices(source, 'fixture')


def test_office_source_rejects_missing_headers(tmp_path):
    source = tmp_path / 'fixture.zip'
    with zipfile.ZipFile(source, 'w') as archive:
        archive.writestr('dummy.csv', 'Organization CRD#\n123\n')
    with pytest.raises(ValueError, match='required office'):
        _bronze_offices(source, 'fixture')


@pytest.mark.parametrize('encoding', ['utf-8-sig', 'cp1252'])
def test_office_source_preserves_text_encodings(tmp_path, encoding):
    source = tmp_path / 'fixture.zip'
    content = io.StringIO()
    writer = csv.DictWriter(content, fieldnames=['Organization CRD#', *OFFICE_FIELDS.values()])
    writer.writeheader()
    writer.writerow({'Organization CRD#':'123','Main Office Street Address 1':'10 Rue Café', 'Main Office Postal Code':'00123'})
    with zipfile.ZipFile(source, 'w') as archive:
        archive.writestr('roster.csv', content.getvalue().encode(encoding))
    office = _bronze_offices(source, 'fixture')['123']
    assert office['main_office_street_address_1'] == '10 Rue Café'
    assert office['main_office_postal_code'] == '00123'

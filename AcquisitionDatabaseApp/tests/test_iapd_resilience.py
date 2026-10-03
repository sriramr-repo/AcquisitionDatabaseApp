import io
import zipfile
from datetime import date

import pytest

from src import iapd, iapd_live, iapd_recovery
from src.iapd_reconciliation import reconcile_values, source_stale


def test_namespace_attributes_and_nested_wrappers():
    xml = b'''<Feed xmlns:a="urn:new"><Individual><Info a:indvlPK="123" a:firstNm=" Jane " a:lastNm="Doe"/><CurrentEmployments><Wrapper><CurrentEmployment orgPK="42" orgNm="Firm"/></Wrapper></CurrentEmployments></Individual></Feed>'''
    row = next(iapd.parse_iapd_xml(io.BytesIO(xml)))
    assert row['individual_crd'] == '123'
    assert row['current_employments'][0]['employer_firm_crd'] == '42'


def test_invalid_person_crd_is_reported():
    issues=[]
    assert list(iapd.parse_iapd_xml(io.BytesIO(b'<Feed><Indvl><Info indvlPK="N/A"/></Indvl></Feed>'),issues=issues)) == []
    assert issues[0]['code'] == 'MISSING_CRD'


def test_malformed_zip_member_is_reported(tmp_path):
    path=tmp_path/'bad.zip'
    with zipfile.ZipFile(path,'w') as archive:
        archive.writestr('readme.txt','ignored')
        archive.writestr('people.xml','<Feed><Indvl>')
    issues=[]
    with pytest.raises(iapd.IAPDFeedUnavailable):
        list(iapd.parse_iapd_zip(path,issues=issues))
    assert {issue['code'] for issue in issues} == {'NON_XML_MEMBER','MALFORMED_XML_MEMBER'}


@pytest.mark.parametrize('text',['Access denied','Name: Jane\nFirm CRD: 123','Cloudflare verification'])
def test_unidentified_page_cannot_inherit_requested_crd(text):
    with pytest.raises(iapd_live.IAPDLiveUnavailable):
        iapd_live.normalize_iapd_live_markdown(text,expected_crd='123')


def test_footer_contact_is_not_person_contact():
    result=iapd_live.normalize_iapd_live_markdown('Individual CRD: 123\nHelp https://sec.gov 800-555-0100')
    assert result['fields']['phone'] is None
    assert result['fields']['website'] is None


def test_multiple_employers_preserved_without_false_conflict():
    rows=[{'snapshot_id':'s','snapshot_date':'2026-09-01','employer_firm_crd':c,'employer_name':c} for c in ['1','2']]
    fields,freshness,conflicts=reconcile_values(rows,{'current_employer_crd':'2','phone':'0','capture_id':'c'},today=date(2026,9,7))
    assert len(fields['current_employers'])==2
    assert fields['current_employer_crd'] is None
    assert conflicts=={}
    assert fields['phone']=='0'
    assert fields['provenance']['phone']['source_id']=='c'


def test_conflict_preserves_monthly_and_live():
    fields,freshness,conflicts=reconcile_values([{'snapshot_date':'2026-09-01','employer_firm_crd':'1'}],{'current_employer_crd':'2'},today=date(2026,9,7))
    assert fields['current_employer_crd']=='1'
    assert freshness=='conflict'
    assert conflicts['current_employer_crd']['live']=='2'


def test_equivalent_registration_date_formats_do_not_create_conflicts():
    monthly = [{
        'snapshot_date': '2026-09-01',
        'employer_firm_crd': '1',
        'registration_date': '2021-05-09',
    }]
    live = {'current_employer_crd': '1', 'registration_date': '5/9/2021'}
    _, freshness, conflicts = reconcile_values(monthly, live, today=date(2026, 9, 7))
    assert freshness == 'monthly_confirmed'
    assert 'registration_date' not in conflicts


def test_missing_stale_and_partial():
    assert reconcile_values([],None)[1]=='missing'
    assert source_stale('bad')
    assert source_stale('2020-01-01')
    assert reconcile_values([],{ 'retrieved_at':'2026-09-01','confidence':'LOW'},today=date(2026,9,7))[1]=='partial'


def test_recovery_uses_live_when_monthly_unavailable(monkeypatch):
    monkeypatch.setattr(iapd_recovery,'run_iapd_monthly',lambda **kw:{'status':'fallback_required'})
    monkeypatch.setattr(iapd_recovery,'discover_compilation',lambda:[])
    monkeypatch.setattr(iapd_recovery,'capture_iapd_live_page',lambda **kw:{'status':'success','individual_crd':kw['individual_crd']})
    result=iapd_recovery.recover(database_url='unused',crds=['123','123'])
    assert len(result['live'])==1
    assert result['live'][0]['status']=='success'


def test_discovery_ignores_untrusted_hosts_and_bad_dates():
    base='https://reports.adviserinfo.sec.gov/reports/CompilationReports/'
    assert iapd_recovery.compilation_dates([base+'IA_INDVL_Feed_08_20_2026.xml.zip',base+'IA_INDVL_Feed_99_20_2026.xml.zip','https://evil.test/IA_INDVL_Feed_08_20_2026.xml.zip'])==[date(2026,8,20)]


def test_batch_bound_enforced_before_network():
    with pytest.raises(ValueError):
        iapd_recovery.recover(database_url='unused',crds=['1','2'],limit=1)


def test_live_address_fills_only_exact_employer_gap():
    from src.iapd_reconciliation import reconcile_values
    monthly = [{'employer_firm_crd':'42', 'snapshot_date':'2026-09-01'}]
    live = {'current_employer_crd':'42', 'business_address':'1 Main Street'}
    fields, _, _ = reconcile_values(monthly, live)
    assert fields['business_address'] == '1 Main Street'
    assert fields['provenance']['business_address']['source_type'] == 'live_page'
    live['current_employer_crd'] = '77'
    fields, _, conflicts = reconcile_values(monthly, live)
    assert fields['business_address'] is None
    assert 'current_employer_crd' in conflicts


def test_real_iapd_layout_extracts_only_current_registration():
    page='''JANE DOE

CRD#: 123

0

Disclosures

Current Registration(s)

[EXAMPLE INC. (CRD#:42)](https://adviserinfo.sec.gov/firm/summary/42)

1 MAIN STREET, BOSTON, MA

Registered with this firm since 1/2/2026

Previous Registration(s)
[OLD INC. (CRD#:77)](https://adviserinfo.sec.gov/firm/summary/77)
'''
    fields=iapd_live.normalize_iapd_live_markdown(page,expected_crd='123')['fields']
    assert fields['full_name']=='JANE DOE'
    assert fields['current_employer_crd']=='42'
    assert fields['registration_date']=='1/2/2026'
    assert fields['disclosure_summary']=='0 disclosures reported'
    assert len(fields['current_employers'])==1


def test_recovery_records_failure_and_continues(monkeypatch):
    errors=[]
    monkeypatch.setattr(iapd_recovery,'record_failure',lambda db,crd,error:errors.append(crd))
    def crawl(**kw):
        if kw['individual_crd']=='1': raise iapd_live.IAPDLiveUnavailable('blocked')
        return {'status':'success'}
    monkeypatch.setattr(iapd_recovery,'capture_iapd_live_page',crawl)
    result=iapd_recovery.recover(database_url='unused',crds=['1','2'],monthly=False)
    assert errors==['1']
    assert result['live'][1]['status']=='success'

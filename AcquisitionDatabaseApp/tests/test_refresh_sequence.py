"""Exercise the real shell wrapper in an isolated root, with all writes mocked."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile
import pytest


def wrapper(tmp_path, failure=None, dry=False, live_status=None, refresh_env=True, refresh_env_text=None, web_env=False, activation=False, adv_member=None):
    root=tmp_path
    (root/'deploy').mkdir(parents=True)
    shutil.copy(Path(__file__).resolve().parents[1]/'deploy/production-refresh.sh',root/'deploy/production-refresh.sh')
    (root/'data/bronze/raw').mkdir(parents=True)
    archive = root/'data/bronze/raw/fixture.zip'
    if adv_member:
        with zipfile.ZipFile(archive, 'w') as handle:
            handle.writestr(adv_member, 'fixture')
    else:
        archive.touch()
    runner=root/'fake-python'
    runner.write_text('''#!'''+sys.executable+'''
import json,os,sys,subprocess
from pathlib import Path
a=sys.argv[1:]
if a[0]=='-c':
 if 'previous_distinct_snapshot' in a[1]: print(''); sys.exit(0)
 sys.exit(subprocess.call([sys.executable,*a]))
label=' '.join(a[:3])
with open(os.environ['CALLS'],'a') as f:f.write(label+'\\n')
if os.environ.get('EXPECTED_ACTIVATION') and len(a)>1 and a[1]=='src.cli':
 expected=os.environ['EXPECTED_ACTIVATION']
 if '--firm-activation-manifest' not in a or a[a.index('--firm-activation-manifest')+1]!=expected:sys.exit(43)
if os.environ.get('FAIL_STAGE')==label:sys.exit(42)
if a[1]=='src.cli':print(json.dumps({'status':'NO_CHANGE','dataset_version':'fixture'}))
elif a[1]=='src.iapd_recovery':print(json.dumps({'status':'success','source_zip':'fixture.zip','source_url':'https://reports.adviserinfo.sec.gov/fixture.zip','snapshot_date':'2026-09-08'}))
elif a[1]=='src.iapd_batch':print(json.dumps({'status':os.environ['LIVE_STATUS']}))
else:print('{}')
''')
    runner.chmod(0o700)
    if refresh_env:
        env_file = root/'deploy/production-refresh.env'
        activation_line = 'IAPD_FIRM_ACTIVATION_MANIFEST=/reviewed/activation.json\n' if activation else ''
        env_file.write_text(refresh_env_text or (
            'DATABASE_URL=postgres://fixture/fixture\n'
            'PUBLISHER_DATABASE_URL=postgres://fixture/fixture\n'
            'SCM_PRODUCTION_DATABASE_FINGERPRINT=' + ('0' * 64) + '\n' + activation_line
        ))
        env_file.chmod(0o600)
    if web_env:
        (root/'web').mkdir()
        (root/'web/.env.local').write_text('PUBLISHER_DATABASE_URL=postgres://fixture/fixture\n')
        (root/'web/.env.local').chmod(0o600)
    env={**os.environ,'SCM_PYTHON':str(runner),'CALLS':str(root/'calls'),'DATABASE_URL':'postgres://fixture/fixture','PUBLISHER_DATABASE_URL':'postgres://fixture/fixture','IAPD_LIVE_BATCH_SIZE':'0'}
    for key in ('ACCOUNT_ID','ACCESS_KEY_ID','SECRET_ACCESS_KEY','BUCKET'): env['CLOUDFLARE_R2_'+key]='fixture'
    if failure:env['FAIL_STAGE']=failure
    if live_status:env.update(IAPD_LIVE_BATCH_SIZE='25',LIVE_STATUS=live_status)
    if activation:env['EXPECTED_ACTIVATION']='/reviewed/activation.json'
    result=subprocess.run(['/bin/bash',str(root/'deploy/production-refresh.sh'),*(['--dry-run'] if dry else [])],env=env,text=True,capture_output=True)
    calls = (root/'calls').read_text().splitlines() if (root/'calls').exists() else []
    return result,calls


def test_refresh_sequence_and_no_live_budget_consumption(tmp_path):
    result,calls=wrapper(tmp_path)
    assert result.returncode==0,result.stderr
    assert calls.index('-m src.iapd_local compare-snapshots') < calls.index('-m src.iapd_change_publisher publish') < calls.index('-m src.iapd_local publish-r2')
    assert not any('src.iapd_batch' in call for call in calls)


@pytest.mark.parametrize('stage',['-m src.refresh_preflight','-m src.iapd_recovery --database-url','-m src.iapd_local compare-snapshots','-m src.iapd_change_publisher publish'])
def test_failed_stage_stops_dependents(tmp_path,stage):
    result,calls=wrapper(tmp_path,stage)
    assert result.returncode!=0
    assert calls[-1]==stage
    assert 'dependent stages were not run' in result.stderr


def test_dry_run_never_executes_mutating_stages(tmp_path):
    result,calls=wrapper(tmp_path,dry=True)
    assert result.returncode==0
    assert calls==['-m src.refresh_preflight --dry-run']


def test_reviewed_activation_manifest_is_forwarded_to_production_refresh(tmp_path):
    result,calls=wrapper(tmp_path,activation=True)
    assert result.returncode==0,result.stderr
    assert '-m src.cli production-refresh' in calls


def test_form_adv_publication_requires_csv_archive(tmp_path):
    xml_result,xml_calls=wrapper(tmp_path/'xml',adv_member='IA_FIRM_SEC_Feed.xml')
    assert xml_result.returncode==0,xml_result.stderr
    assert '-m src.adv_facts publish' not in xml_calls
    assert 'no validated SEC IA CSV ZIP' in xml_result.stdout

    csv_result,csv_calls=wrapper(tmp_path/'csv',adv_member='IA_ADV_Base_A_20260701.csv')
    assert csv_result.returncode==0,csv_result.stderr
    assert '-m src.adv_facts publish' in csv_calls


def test_missing_refresh_environment_file_blocks_inherited_database_urls(tmp_path):
    result,calls=wrapper(tmp_path,refresh_env=False)
    assert result.returncode!=0
    assert calls==[]
    assert 'environment file not found' in result.stderr


def test_refresh_never_falls_back_to_web_environment(tmp_path):
    result,calls=wrapper(
        tmp_path,
        refresh_env_text='DATABASE_URL=postgres://fixture/fixture\n',
        web_env=True,
    )
    assert result.returncode!=0
    assert calls==[]
    assert 'PUBLISHER_DATABASE_URL must be set' in result.stderr


@pytest.mark.parametrize('status',['partial','paused','failed'])
def test_partial_live_batch_is_not_successful_refresh(tmp_path,status):
    result,calls=wrapper(tmp_path,live_status=status)
    assert result.returncode!=0
    assert 'Production refresh stages completed.' not in result.stdout
    assert 'iapd_live_batch' in result.stderr

"""Exercise the real shell wrapper in an isolated root, with all writes mocked."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import pytest


def wrapper(tmp_path, failure=None, dry=False, live_status=None):
    root=tmp_path
    (root/'deploy').mkdir()
    shutil.copy(Path(__file__).resolve().parents[1]/'deploy/production-refresh.sh',root/'deploy/production-refresh.sh')
    (root/'data/bronze/raw').mkdir(parents=True)
    (root/'data/bronze/raw/fixture.zip').touch()
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
if os.environ.get('FAIL_STAGE')==label:sys.exit(42)
if a[1]=='src.cli':print(json.dumps({'status':'NO_CHANGE','dataset_version':'fixture'}))
elif a[1]=='src.iapd_recovery':print(json.dumps({'status':'success','source_zip':'fixture.zip','source_url':'https://reports.adviserinfo.sec.gov/fixture.zip','snapshot_date':'2026-09-08'}))
elif a[1]=='src.iapd_batch':print(json.dumps({'status':os.environ['LIVE_STATUS']}))
else:print('{}')
''')
    runner.chmod(0o700)
    env={**os.environ,'SCM_PYTHON':str(runner),'CALLS':str(root/'calls'),'DATABASE_URL':'postgres://fixture/fixture','PUBLISHER_DATABASE_URL':'postgres://fixture/fixture','IAPD_LIVE_BATCH_SIZE':'0'}
    for key in ('ACCOUNT_ID','ACCESS_KEY_ID','SECRET_ACCESS_KEY','BUCKET'): env['CLOUDFLARE_R2_'+key]='fixture'
    if failure:env['FAIL_STAGE']=failure
    if live_status:env.update(IAPD_LIVE_BATCH_SIZE='25',LIVE_STATUS=live_status)
    result=subprocess.run(['/bin/bash',str(root/'deploy/production-refresh.sh'),*(['--dry-run'] if dry else [])],env=env,text=True,capture_output=True)
    return result,(root/'calls').read_text().splitlines()


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


@pytest.mark.parametrize('status',['partial','paused','failed'])
def test_partial_live_batch_is_not_successful_refresh(tmp_path,status):
    result,calls=wrapper(tmp_path,live_status=status)
    assert result.returncode!=0
    assert 'Production refresh stages completed.' not in result.stdout
    assert 'iapd_live_batch' in result.stderr

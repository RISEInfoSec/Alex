from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest

from tests.test_content_review_source_pending import fixture,call
from tests.test_content_review_verified_inputs import git

ROOT=Path(__file__).resolve().parents[1]


def value(repo, *, failed=False):
    values=list(fixture(repo))
    if failed:values[-1].update(status='source_run_failed',source_run_id=123,conclusion='failure')
    now,review,main,hb,native,snapshot,reservation,discovery=values;proposal=call(repo,values)
    before=json.loads(git(repo,'show',review+':config/content_review_worker_status.json'));rid=before['current_run']['pending_source_request']['request_id']
    return {'before':before,'after':json.loads(proposal['files']['config/content_review_worker_status.json']),
       'receipt':json.loads(proposal['files'][proposal['receipt_path']]),'request':json.loads(git(repo,'show',review+':config/content_review_source_requests/'+rid+'.json')),
       'discovery':discovery,'snapshot':snapshot,'confirmed':deepcopy(snapshot),'owner':'worker','runId':'run','now':int(now.timestamp()*1000)}


def invoke(data):
    code="""const {validateSourcePending}=require('./tools/content_review/site_source_pending_guard.cjs');let s='';
process.stdin.on('data',x=>s+=x).on('end',()=>{try{process.stdout.write(JSON.stringify(validateSourcePending(JSON.parse(s))))}
catch(e){process.stderr.write(e.message);process.exitCode=1}});"""
    return subprocess.run(['node','-e',code],cwd=ROOT,input=json.dumps(data,ensure_ascii=False),text=True,capture_output=True)


def test_site_guard_accepts_exact_pending_deferral_and_no_processing(tmp_path):
    result=invoke(value(tmp_path));assert result.returncode==0,result.stderr
    checked=json.loads(result.stdout);assert checked['candidate_processing'] is False and checked['native_completion_verified'] is False


def test_site_guard_holds_failed_source_and_rejects_unknown_usage_or_hold_tampering(tmp_path):
    data=value(tmp_path,failed=True);result=invoke(data)
    assert result.returncode==0,result.stderr
    changed=deepcopy(data);changed['receipt']['origin_provider_requests']=0
    assert invoke(changed).returncode!=0
    changed=deepcopy(data);changed['after']['source_unresolved_requests'][0]['origin_hosts']=[]
    assert invoke(changed).returncode!=0
    changed=deepcopy(data);changed['after']['current_run']['pending_source_request']=data['before']['current_run']['pending_source_request']
    assert invoke(changed).returncode!=0


@pytest.mark.parametrize('change',['ready','request','state','receipt','snapshot','budget','late'])
def test_site_guard_rejects_unsafe_pending_deferral(tmp_path,change):
    d=value(tmp_path)
    if change=='ready':d['discovery']['status']='source_artifact_ready'
    if change=='request':d['request']['records'][0]['url']='https://different.example/'
    if change=='state':d['after']['current_run']['pending_source_request']=None
    if change=='receipt':d['receipt']['candidate_processing']=True
    if change=='snapshot':d['confirmed']['read_evidence']['jobs']['complete']=False
    if change=='budget':d['before']['current_run']['request_counts']['source']=1
    if change=='late':d['now']+=181000
    assert invoke(d).returncode!=0

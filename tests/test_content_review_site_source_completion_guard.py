from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest

from tests.test_content_review_source_completion import fixture,call
from tests.test_content_review_verified_inputs import git

ROOT=Path(__file__).resolve().parents[1]


def value(repo):
    values=fixture(repo);now,review,main,hb,native,snapshot,rid,raw,run,artifact=values
    proposal=call(repo,values);artifact['archive_sha256']='f'*64
    return {'before':json.loads(git(repo,'show',review+':config/content_review_worker_status.json')),
            'after':json.loads(proposal['files']['config/content_review_worker_status.json']),
            'receipt':json.loads(proposal['files'][proposal['receipt_path']]),
            'sourceReceipt':json.loads(git(repo,'show',review+':config/content_review_source_receipts/'+rid+'.json')),
            'artifact':artifact,'nativeRun':run,'resultText':raw.decode(),'snapshot':snapshot,'confirmed':deepcopy(snapshot),
            'owner':'worker','runId':'run','now':int(now.timestamp()*1000)}


def invoke(data):
    code="""const {validateSourceCompletion}=require('./tools/content_review/site_source_completion_guard.cjs');let s='';
process.stdin.on('data',x=>s+=x).on('end',()=>{try{process.stdout.write(JSON.stringify(validateSourceCompletion(JSON.parse(s))))}
catch(e){process.stderr.write(e.message);process.exitCode=1}});"""
    return subprocess.run(['node','-e',code],cwd=ROOT,input=json.dumps(data,ensure_ascii=False),text=True,capture_output=True)


def test_site_guard_accepts_python_source_deferral_without_claiming_gate(tmp_path):
    result=invoke(value(tmp_path));assert result.returncode==0,result.stderr
    checked=json.loads(result.stdout)
    assert checked['candidate_processing'] is False and checked['native_completion_verified'] is False


@pytest.mark.parametrize('change',['artifact','receipt','state','native','snapshot','budget','count','late'])
def test_site_guard_rejects_forged_or_stale_completion(tmp_path,change):
    d=value(tmp_path)
    if change=='artifact':d['artifact']['sha256']='a'*64
    if change=='receipt':d['receipt']['candidate_processing']=True
    if change=='state':d['after']['lease_history']=[]
    if change=='native':d['nativeRun']['conclusion']='failure'
    if change=='snapshot':d['confirmed']['read_evidence']['jobs']['complete']=False
    if change=='budget':d['before']['current_run']['request_counts']['source']+=1
    if change=='count':d['sourceReceipt']['result']['requests']+=1
    if change=='late':d['now']+=181000
    assert invoke(d).returncode!=0


def test_late_accounted_source_releases_only_with_original_run_history():
    from datetime import datetime,timezone
    from tests.test_content_review_site_source_result_guard import value as accounting_value
    from tools.content_review.lease import release
    v=accounting_value(late=True);now=datetime.fromtimestamp(v['now']/1000,timezone.utc)
    state=deepcopy(v['after']);run=state['current_run'];run['scheduled_for']=run['started_at']
    state['lease']['acquired_at']=run['started_at'];stamp=now.isoformat();path='config/content_review_run_receipts/next-run.json'
    after=release(state,'next-worker','next-run',at=now);after['current_run']['application_status']='deferred'
    after['current_run']['application_completed_at']=stamp;after['current_run']['receipt']=path
    receipt={'schema_version':1,'kind':'source_evidence_deferral','run_id':'next-run','trigger':'schedule',
        'scheduled_for':run['scheduled_for'],'started_at':run['started_at'],'completed_at':stamp,'status':'deferred','receipt_path':path,
        'source_request_id':v['request']['request_id'],'source_requests':0,'source_workflow_verified':True,'candidate_processing':False,
        'gate_passed':False,'native_completion_verified':False,'publication_approved':False,
        'scope_note':'Source retrieval was accounted; candidate gates, review readiness and publication are not established.'}
    d={'before':state,'after':after,'receipt':receipt,'sourceReceipt':v['receipt'],'artifact':v['artifact'],'nativeRun':v['nativeRun'],
       'resultText':v['resultText'],'snapshot':v['snapshot'],'confirmed':v['confirmed'],'owner':'next-worker','runId':'next-run','now':v['now']}
    result=invoke(d);assert result.returncode==0,result.stderr
    d['before']['run_history']=[]
    assert invoke(d).returncode!=0

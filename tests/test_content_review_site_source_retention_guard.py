from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest

from tests.test_content_review_source_retention import fixture, call
from tools.content_review.source_retention_checkpoint import prepare as checkpoint

ROOT=Path(__file__).resolve().parents[1]


def value(repo):
    now,review,main,hb,snapshot,request,raw,run,artifact=fixture(repo)
    proposal=call(repo,now,review,main,hb,snapshot,request,raw,run,artifact)
    item=request['records'][0]
    result=checkpoint(repo,review,main,hb,snapshot,deepcopy(snapshot),request['request_id'],raw,run,artifact,
        item['collection'],item['candidate_id'],'worker','run',proposal,observed_heads={'review':review,'main':main},at=now)
    state=json.loads((repo/'config/content_review_worker_status.json').read_text())
    return {'before':json.loads((repo/proposal['path']).read_text()),'after':json.loads(proposal['content']),
        'state':state,'afterState':deepcopy(state),'request':request,
        'sourceReceipt':json.loads((repo/('config/content_review_source_receipts/'+request['request_id']+'.json')).read_text()),
        'receipt':json.loads(result['bundle']['files'][result['proof']['new_path']]),'nativeRun':run,'artifact':artifact,
        'resultText':raw.decode(),'snapshot':snapshot,'confirmed':deepcopy(snapshot),'owner':'worker','runId':'run',
        'now':int(now.timestamp()*1000)}


def invoke(data):
    code="""const {validateSourceRetention}=require('./tools/content_review/site_source_retention_guard.cjs');let s='';
process.stdin.on('data',x=>s+=x).on('end',()=>{try{process.stdout.write(JSON.stringify(validateSourceRetention(JSON.parse(s))))}
catch(e){process.stderr.write(e.message);process.exitCode=1}});"""
    return subprocess.run(['node','-e',code],cwd=ROOT,input=json.dumps(data,ensure_ascii=False),text=True,capture_output=True)


def test_independent_guard_accepts_python_retention_without_passing_a_gate(tmp_path):
    result=invoke(value(tmp_path));assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['gate_passed'] is False


@pytest.mark.parametrize('change',['manifest','state','artifact','receipt','result','review','lease','lease_time','accounting'])
def test_independent_guard_rejects_unverified_or_unrelated_changes(tmp_path,change):
    d=value(tmp_path)
    if change=='manifest':d['after']['records'][0]['decision']='approved'
    if change=='state':d['afterState']['current_run']['application_status']='completed'
    if change=='artifact':d['artifact']['sha256']='f'*64
    if change=='receipt':d['receipt']['publication_approved']=True
    if change=='result':d['resultText']+=' '
    if change=='review':d['confirmed']['read_evidence']['decisions']['complete']=False
    if change=='lease':d['state']['lease']['owner']='someone-else';d['afterState']['lease']['owner']='someone-else'
    if change=='lease_time':d['state']['lease']['expires_at']='invalid';d['afterState']=deepcopy(d['state'])
    if change=='accounting':d['state']['current_run']['accounted_source_requests']=[];d['afterState']=deepcopy(d['state'])
    assert invoke(d).returncode!=0


def test_guard_refuses_matching_private_decision_even_when_snapshot_is_stable(tmp_path):
    d=value(tmp_path)
    item=d['request']['records'][0]
    submission={'id':'s','user_id':'private-user','collection':item['collection'],'batch':1,
                'revision':1,'accepted':0,'rejected':1,'payload_hash':'a'*64}
    decision={'id':'d','submission_id':'s','user_id':'private-user','collection':item['collection'],'batch':1,
              'revision':1,'candidate_id':item['candidate_id'],'review_number':1,
              'content_sha256':item['content_sha256'],'decision':'rejected'}
    d['snapshot']['submissions']=[submission];d['snapshot']['decisions']=[decision]
    for key in ('submissions','decisions'):d['snapshot']['read_evidence'][key]['rows_received']=1
    d['confirmed']=deepcopy(d['snapshot'])
    result=invoke(d)
    assert result.returncode!=0 and 'review state' in result.stderr

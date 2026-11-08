from copy import deepcopy
import hashlib
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


def test_source_retention_preserves_existing_quality_hold(tmp_path):
    data=value(tmp_path)
    old=data['before']['records'][0];new=data['after']['records'][0]
    held={'status':'held','content_sha256':old['content_sha256'],'checked_at':'2026-11-08T00:00:00Z',
          'evidence':{'quality_review_status':'hold_core_term_gate'}}
    old['preflight']['checks']['quality']=deepcopy(held)
    new['preflight']['checks']['quality']=deepcopy(held)
    result=invoke(data);assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['gate_passed'] is False
    new['preflight']['checks']['quality']['status']='passed'
    assert invoke(data).returncode!=0


def reserved_soups(data):
    from tools.content_review.source_worker import digest
    req=data['request'];item=req['records'][0];item['collection']='soups'
    req['request_id']=digest({k:v for k,v in req.items() if k!='request_id'});rid=req['request_id']
    result=json.loads(data['resultText']);result['request_id']=rid;result['records'][0]['collection']='soups'
    raw=json.dumps(result,ensure_ascii=False);sha=hashlib.sha256(raw.encode()).hexdigest();data['resultText']=raw
    data['artifact']['sha256']=sha
    data['sourceReceipt'].update(request=deepcopy(req),result=deepcopy(result),artifact_sha256=sha)
    data['receipt'].update(collection='soups',request_id=rid,artifact_sha256=sha)
    for state in (data['state'],data['afterState']):
        entry=state['current_run']['accounted_source_requests'][0];entry['request_id']=rid;entry['artifact_sha256']=sha
    for manifest in (data['before'],data['after']):
        row=manifest['records'][0];row.pop('review_number',None);row.pop('review_batch',None);row.pop('batch',None)
        row.update(reserved_review_number=121,reserved_review_batch=8)
    data['after']['records'][0]['source_processing']['receipt']='config/content_review_source_receipts/'+rid+'.json'
    return data


def test_reserved_soups_retention_preserves_intake_identity_and_checks_decisions(tmp_path):
    data=reserved_soups(value(tmp_path));result=invoke(data)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['gate_passed'] is False
    collision=deepcopy(data)
    for manifest in (collision['before'],collision['after']):
        manifest['records'].append({'candidate_id':'other','review_number':121})
    assert invoke(collision).returncode!=0
    reviewed=deepcopy(data)
    reviewed['snapshot']['submissions']=[{'id':'s','user_id':'owner','collection':'soups','batch':8,
        'revision':1,'accepted':0,'rejected':1,'payload_hash':'a'*64}]
    reviewed['snapshot']['read_evidence']['submissions']['rows_received']=1
    reviewed['confirmed']=deepcopy(reviewed['snapshot'])
    assert invoke(reviewed).returncode!=0


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

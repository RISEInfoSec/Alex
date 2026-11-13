from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from tests.test_content_review_source_plan import fixture, call, quality_fixture
from tools.content_review.source_worker import digest
from tools.content_review.verified_inputs import load_inputs

ROOT=Path(__file__).resolve().parents[1]


def value(repo):
    now,review,main,hb,row,snapshot=fixture(repo);proposal=call(repo,now,review,main,hb,snapshot)
    inputs=load_inputs(repo,review,main)
    return {'before':inputs['worker_state'],'after':proposal['reserved_state'],'request':proposal['request'],
            'manifests':inputs['manifests'],'manifestHashes':{'weekly':hashlib.sha256((repo/'config/weekly_review_manifest.json').read_bytes()).hexdigest()},
            'ledger':inputs['lifecycle'],'snapshot':snapshot,'confirmed':deepcopy(snapshot),'owner':'worker','runId':'run',
            'now':int(now.timestamp()*1000)}


def quality_value(repo):
    from tools.content_review.source_plan import prepare
    now,review,main,hb,row,snapshot=quality_fixture(repo)
    proposal=prepare(repo,review,main,hb,snapshot,deepcopy(snapshot),'worker','run',
                     observed_heads={'review':review,'main':main},at=now,quality_evidence=True)
    inputs=load_inputs(repo,review,main)
    return {'before':inputs['worker_state'],'after':proposal['reserved_state'],'request':proposal['request'],
            'manifests':inputs['manifests'],'manifestHashes':{'weekly':hashlib.sha256((repo/'config/weekly_review_manifest.json').read_bytes()).hexdigest()},
            'ledger':inputs['lifecycle'],'snapshot':snapshot,'confirmed':deepcopy(snapshot),'owner':'worker','runId':'run',
            'now':int(now.timestamp()*1000)}


def test_site_independently_checks_quality_evidence_request(tmp_path):
    data=quality_value(tmp_path);result=invoke(data)
    assert result.returncode==0,result.stderr
    checked=json.loads(result.stdout)
    assert checked['candidate_processing'] is False and checked['publication_verified'] is False
    assert data['manifests']['weekly']['records'][0]['preflight']['checks']['quality']['status']=='held'


@pytest.mark.parametrize('change',['decision','changed_snapshot','stale','quality_passed','prior_gate','retained','purpose'])
def test_site_rejects_unsafe_quality_evidence_request(tmp_path,change):
    data=quality_value(tmp_path);row=data['manifests']['weekly']['records'][0]
    if change=='decision':row['decision']='rejected'
    if change=='changed_snapshot':data['confirmed']['read_evidence']['decisions']['complete']=False
    if change=='stale':row['preflight']['checks']['quality']['content_sha256']='f'*64
    if change=='quality_passed':row['preflight']['checks']['quality']['status']='passed'
    if change=='prior_gate':row['preflight']['checks']['access']['status']='held'
    if change=='retained':row['source_processing']={'content_sha256':row['content_sha256'],'retrieval_status':'retrieved'}
    if change=='purpose':data['request']['purpose']='unrelated';resign(data)
    assert invoke(data).returncode!=0


def invoke(data):
    code="""const {validateSourceRequest}=require('./tools/content_review/site_source_request_guard.cjs');let s='';
process.stdin.on('data',x=>s+=x).on('end',()=>{try{process.stdout.write(JSON.stringify(validateSourceRequest(JSON.parse(s))));}
catch(e){process.stderr.write(e.message);process.exitCode=1;}});"""
    return subprocess.run(['node','-e',code],cwd=ROOT,input=json.dumps(data,ensure_ascii=False),text=True,capture_output=True)


def resign(data):
    request=data['request'];request['request_id']=digest({k:v for k,v in request.items() if k!='request_id'})
    data['after']['current_run']['pending_source_request']['request_id']=request['request_id']


def test_site_guard_accepts_a_real_bounded_python_source_request(tmp_path):
    result=invoke(value(tmp_path));assert result.returncode==0,result.stderr
    checked=json.loads(result.stdout)
    assert checked['status']=='valid' and checked['source_request_limit']==30
    assert checked['candidate_processing'] is False and checked['publication_verified'] is False


def test_site_guard_refuses_active_origin_backoff_and_retained_holds(tmp_path):
    original=value(tmp_path);data=deepcopy(original)
    backoff={'example.org':{'reason':'http_429','retry_not_before':'2099-01-01T00:00:00Z','source_request_id':'a'*64}}
    data['before']['source_origin_backoff']=deepcopy(backoff);data['after']['source_origin_backoff']=deepcopy(backoff)
    assert invoke(data).returncode!=0
    data=deepcopy(original)
    row=data['manifests']['weekly']['records'][0]
    row['source_processing']={'content_sha256':row['content_sha256'],'retrieval_status':'held'}
    assert invoke(data).returncode!=0


def test_site_guard_blocks_all_source_requests_when_redirect_history_is_unknown(tmp_path):
    from tests.test_content_review_source_unresolved import sample
    from tools.content_review.source_unresolved import from_failure
    data=value(tmp_path);request,pending,discovery=sample()
    request['records']=request['records'][:1]
    request['records'][0].update(candidate_id='different-candidate',url='https://different.example/paper')
    request['request_id']=digest({k:v for k,v in request.items() if k!='request_id'});pending['request_id']=request['request_id']
    hold=from_failure(request,pending,discovery)
    for state in (data['before'],data['after']):state['source_unresolved_requests']=[deepcopy(hold)]
    result=invoke(data)
    assert result.returncode!=0 and 'requires reconciliation' in result.stderr.lower()


def test_reserved_soups_identity_allows_source_but_rejects_collision_and_review_state(tmp_path):
    data=value(tmp_path)
    data['manifests']['soups']=data['manifests'].pop('weekly')
    data['manifestHashes']['soups']=data['manifestHashes'].pop('weekly')
    item=data['request']['records'][0];item['collection']='soups'
    row=data['manifests']['soups']['records'][0]
    row.pop('review_number',None);row.pop('review_batch',None);row.pop('batch',None)
    row.update(reserved_review_number=201,reserved_review_batch=11)
    data['ledger']['records']['soups:'+item['candidate_id']]=data['ledger']['records'].pop('weekly:'+item['candidate_id'])
    resign(data)
    result=invoke(data);assert result.returncode==0,result.stderr
    collided=deepcopy(data)
    collided['manifests']['soups']['records'].append({'candidate_id':'other','review_number':201})
    assert invoke(collided).returncode!=0
    reviewed=deepcopy(data)
    for snap in (reviewed['snapshot'],reviewed['confirmed']):
        snap['submissions']=[{'id':'s','user_id':'owner','collection':'soups','batch':11,'revision':1,
                              'accepted':0,'rejected':1,'payload_hash':'a'*64}]
        snap['decisions']=[{'id':'d','submission_id':'s','user_id':'owner','collection':'soups','batch':11,'revision':1,
                            'candidate_id':item['candidate_id'],'review_number':201,'content_sha256':row['content_sha256'],'decision':'rejected'}]
        for k in ('submissions','decisions'):snap['read_evidence'][k]['rows_received']=1
    assert invoke(reviewed).returncode!=0


@pytest.mark.parametrize('change',['url','openalex','hash','budget','state','snapshot','decision','retrieved','duplicate','expired'])
def test_site_guard_rejects_unchecked_source_requests(tmp_path,change):
    data=value(tmp_path)
    if change=='url':data['request']['records'][0]['url']='https://other.example/' ;resign(data)
    if change=='openalex':
        data['request']['records'][0]['url']='https://api.openalex.org/works/example'
        data['manifests']['weekly']['records'][0]['source_url']='https://api.openalex.org/works/example';resign(data)
    if change=='hash':data['request']['records'][0]['manifest_sha256']='f'*64;resign(data)
    if change=='budget':data['request']['source_request_limit']=31;resign(data)
    if change=='state':data['after']['current_run']['request_counts']['source']=0;data['after']['lease']['owner']='other'
    if change=='snapshot':data['confirmed']['read_evidence']['decisions']['complete']=False
    if change=='retrieved':
        row=data['manifests']['weekly']['records'][0];row['source_processing']={'content_sha256':row['content_sha256'],'retrieval_status':'retrieved'}
    if change=='duplicate':data['request']['records'].append(deepcopy(data['request']['records'][0]));resign(data)
    if change=='expired':data['now']+=181000
    if change=='decision':
        row=data['manifests']['weekly']['records'][0]
        for snap in (data['snapshot'],data['confirmed']):
            snap['submissions']=[{'id':'s','user_id':'owner','collection':'weekly','batch':1,'revision':1,
                                  'accepted':0,'rejected':1,'payload_hash':'a'*64}]
            snap['decisions']=[{'id':'d','submission_id':'s','user_id':'owner','collection':'weekly','batch':1,'revision':1,
                                'candidate_id':row['candidate_id'],'review_number':1,'content_sha256':row['content_sha256'],'decision':'rejected'}]
            for k in ('submissions','decisions'):snap['read_evidence'][k]['rows_received']=1
    assert invoke(data).returncode!=0

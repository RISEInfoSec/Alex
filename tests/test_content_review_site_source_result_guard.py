from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from tests.test_content_review_source_accounting import fixture
from tools.content_review.source_accounting import prepare

ROOT=Path(__file__).resolve().parents[1]


def value(late=False):
    now,state,request,raw,run,artifact=fixture();owner,run_id='worker','scheduler-run'
    if late:
        old=deepcopy(state['current_run']);old['application_status']='failed';state['run_history']=[old]
        state['lease_history']=[{'owner':'worker','run_id':'scheduler-run','status':'released'}]
        state['lease']={'owner':'next-worker','run_id':'next-run','expires_at':state['lease']['expires_at']}
        state['current_run']={'run_id':'next-run','application_status':'running','started_at':now.isoformat(),
            'request_counts':{'source':0,'paid':0,'openalex':0},'pending_source_request':deepcopy(old['pending_source_request'])}
        owner,run_id='next-worker','next-run'
    proposal=prepare(state,request,raw,run,artifact,owner,run_id,at=now)
    snap={'submissions':[],'decisions':[],'jobs':[]}
    snap['read_evidence']={k:{'complete':True,'rows_received':0,'truncated_values':0,'omitted_columns':0}
                           for k in ('submissions','decisions','jobs')}
    artifact['archive_sha256']='e'*64
    return {'before':state,'after':proposal['state'],'request':request,'receipt':proposal['receipt'],'nativeRun':run,'artifact':artifact,
            'resultText':raw.decode('utf8'),'snapshot':snap,'confirmed':deepcopy(snap),'owner':owner,'runId':run_id,'now':int(now.timestamp()*1000)}


def invoke(data):
    code="""const {validateSourceResult}=require('./tools/content_review/site_source_result_guard.cjs');let s='';
process.stdin.on('data',x=>s+=x).on('end',()=>{try{process.stdout.write(JSON.stringify(validateSourceResult(JSON.parse(s))));}
catch(e){process.stderr.write(e.message);process.exitCode=1;}});"""
    return subprocess.run(['node','-e',code],cwd=ROOT,input=json.dumps(data,ensure_ascii=False),text=True,capture_output=True)


@pytest.mark.parametrize('late',[False,True])
def test_site_guard_matches_python_source_accounting_including_carried_request(late):
    result=invoke(value(late));assert result.returncode==0,result.stderr
    parsed=json.loads(result.stdout)
    assert parsed['status']=='valid' and parsed['source_requests']==2
    assert parsed['candidate_processing'] is False and parsed['publication_verified'] is False


@pytest.mark.parametrize('change',['artifact','archive','run','state','receipt','snapshot','provenance','count','pending','history'])
def test_site_guard_rejects_unverified_result_or_changed_accounting(change):
    data=value(late=change=='history')
    if change=='artifact':data['artifact']['sha256']='f'*64
    if change=='archive':data['artifact']['archive_sha256']='missing'
    if change=='run':data['nativeRun']['conclusion']='failure'
    if change=='state':data['after']['current_run']['request_counts']['source']+=1
    if change=='receipt':data['receipt']['result']['status']='forged'
    if change=='snapshot':data['confirmed']['read_evidence']['jobs']['complete']=False
    if change=='provenance':
        result=json.loads(data['resultText']);result['provenance']['GITHUB_RUN_ID']='different';data['resultText']=json.dumps(result)
        data['artifact']['sha256']=hashlib.sha256(data['resultText'].encode()).hexdigest()
    if change=='count':
        result=json.loads(data['resultText']);result['requests']=3;data['resultText']=json.dumps(result)
        data['artifact']['sha256']=hashlib.sha256(data['resultText'].encode()).hexdigest()
    if change=='pending':data['before']['current_run']['pending_source_request']['reserved_limit']=29
    if change=='history':data['before']['lease_history']=[]
    assert invoke(data).returncode!=0

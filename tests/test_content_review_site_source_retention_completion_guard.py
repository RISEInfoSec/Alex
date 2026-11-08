from copy import deepcopy
import json,subprocess
from pathlib import Path

import pytest
from tests.test_content_review_source_retention_run_completion import fixture,call

ROOT=Path(__file__).resolve().parents[1]


def value(repo,result_status='retrieved'):
    values=fixture(repo,result_status);result=call(repo,values)
    receipt=json.loads(result['files'][result['receipt_path']]);after=json.loads(result['files']['config/content_review_worker_status.json'])
    before=json.loads(subprocess.check_output(['git','-C',str(repo),'show',values[1]+':config/content_review_worker_status.json']))
    return {'before':before,'after':after,'receipt':receipt,'owner':'worker','runId':'run2',
            'verifiedAction':deepcopy(receipt['completed_actions'][0]),'now':int(values[0].timestamp()*1000)}


def invoke(data):
    code="const g=require('./tools/content_review/site_source_retention_completion_guard.cjs');let s='';" \
         "process.stdin.on('data',x=>s+=x).on('end',()=>{try{process.stdout.write(JSON.stringify(g.validateSourceRetentionCompletion(JSON.parse(s))))}" \
         "catch(e){process.stderr.write(e.message);process.exitCode=1}});"
    return subprocess.run(['node','-e',code],cwd=ROOT,input=json.dumps(data),text=True,capture_output=True)


def test_site_validates_truthful_source_retention_completion(tmp_path):
    result=invoke(value(tmp_path));assert result.returncode==0,result.stderr
    checked=json.loads(result.stdout)
    assert checked['candidate_processing'] is True and checked['native_completion_verified'] is False


def test_site_validates_hold_without_accepting_false_progress(tmp_path):
    data=value(tmp_path,'held');result=invoke(data)
    assert result.returncode==0,result.stderr
    checked=json.loads(result.stdout)
    assert checked['candidate_processing'] is False and checked['native_completion_verified'] is False
    data['receipt']['candidate_processing']=True
    assert invoke(data).returncode!=0


@pytest.mark.parametrize('change',['action','receipt','native','publication','state','lease','counts'])
def test_retention_completion_rejects_unverified_or_unrelated_changes(tmp_path,change):
    data=value(tmp_path)
    if change=='action':data['verifiedAction']['content_sha256']='0'*64
    if change=='receipt':data['receipt']['completed_actions']=[]
    if change=='native':data['receipt']['native_completion_verified']=True
    if change=='publication':data['receipt']['publication_approved']=True
    if change=='state':data['after']['last_error']='invented'
    if change=='lease':data['before']['lease']['owner']='other'
    if change=='counts':data['before']['current_run']['request_counts']['paid']=1
    assert invoke(data).returncode!=0

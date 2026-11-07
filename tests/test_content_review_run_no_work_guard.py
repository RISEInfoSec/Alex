from copy import deepcopy
from datetime import timedelta
import json
from pathlib import Path
import subprocess

import pytest

from tests.test_content_review_run_completion import fixture, call
from tests.test_content_review_verified_inputs import git

ROOT=Path(__file__).resolve().parents[1]


def setup(repo):
    data=fixture(repo,with_checkpoint=False);result=call(repo,data)
    before=json.loads(git(repo,'show',data[1]+':config/content_review_worker_status.json'))
    after=json.loads(result['files']['config/content_review_worker_status.json'])
    receipt=json.loads(result['files'][result['new_path']])
    return {'before':before,'after':after,'receipt':receipt,'owner':'worker','runId':'run',
            'now':int((data[0]+timedelta(seconds=10)).timestamp()*1000)}


def invoke(value):
    code="""const {validateNoWork}=require('./tools/content_review/run_no_work_guard.cjs');
let s='';process.stdin.on('data',x=>s+=x).on('end',()=>{try{process.stdout.write(JSON.stringify(validateNoWork(JSON.parse(s))));}
catch(e){process.stderr.write(e.message);process.exitCode=1;}});"""
    return subprocess.run(['node','-e',code],cwd=ROOT,input=json.dumps(value),text=True,capture_output=True)


def test_real_no_work_completion_is_never_a_candidate_or_native_success(tmp_path):
    result=invoke(setup(tmp_path))
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)=={'status':'valid','candidate_processing':False,'native_completion_verified':False}


@pytest.mark.parametrize('change',['work','private','history','lease','timing','counts'])
def test_no_work_completion_rejects_fabricated_evidence_or_lost_history(tmp_path,change):
    value=setup(tmp_path)
    if change=='work':value['receipt']['completed_actions']=[{'candidate_id':'invented'}]
    if change=='private':value['receipt']['private_row']='not permitted'
    if change=='history':value['after']['run_history']=[]
    if change=='lease':value['after']['lease_history'][-1]['owner']='other'
    if change=='timing':value['now']+=41000
    if change=='counts':value['before']['current_run']['request_counts']['paid']=1
    assert invoke(value).returncode!=0

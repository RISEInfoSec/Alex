import json
from copy import deepcopy
from pathlib import Path
import subprocess

import pytest

from tests.test_content_review_run_completion import call, fixture
from tests.test_content_review_verified_inputs import git

ROOT = Path(__file__).resolve().parents[1]


def value(repo):
    data = fixture(repo)
    result = call(repo, data)
    receipt = json.loads(result['files'][result['new_path']])
    return {'before':json.loads(git(repo,'show',data[1]+':config/content_review_worker_status.json')),
            'after':json.loads(result['files']['config/content_review_worker_status.json']),
            'receipt':receipt,'owner':'worker','runId':'run',
            'verifiedAction':deepcopy(receipt['completed_actions'][0]), 'now':int((data[0].timestamp()+10)*1000)}


def invoke(data):
    code="""const {validateComplete}=require('./tools/content_review/site_run_complete_guard.cjs');let s='';
process.stdin.on('data',x=>s+=x).on('end',()=>{try{process.stdout.write(JSON.stringify(validateComplete(JSON.parse(s))));}
catch(e){process.stderr.write(e.message);process.exitCode=1;}});"""
    return subprocess.run(['node','-e',code],cwd=ROOT,input=json.dumps(data),text=True,capture_output=True)


def test_site_guard_validates_real_completed_checkpoint_receipt(tmp_path):
    data=value(tmp_path);result=invoke(data)
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)=={'status':'valid','candidate_processing':True,
                                       'native_completion_verified':False,'publication_verified':False}


@pytest.mark.parametrize('change',['action','native','publication','history','state','request','empty','expired'])
def test_site_guard_refuses_false_completion_claims(tmp_path,change):
    data=value(tmp_path)
    if change=='action':data['verifiedAction']['content_sha256']='f'*64
    if change=='native':data['receipt']['native_completion_verified']=True
    if change=='publication':data['receipt']['publication_approved']=True
    if change=='history':data['after']['lease_history']=[]
    if change=='state':data['after']['phase']='forged'
    if change=='request':data['receipt']['provider_requests']=1
    if change=='empty':data['receipt']['completed_actions']=[]
    if change=='expired':data['now']+=301000
    assert invoke(data).returncode!=0

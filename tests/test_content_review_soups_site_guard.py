from copy import deepcopy
import json
from pathlib import Path
import subprocess

import pytest

from tests.test_content_review_soups_intake_guard import fixture
from tools.content_review.soups_intake_guard import prepare as guard
from tools.content_review.verified_inputs import load_inputs

ROOT = Path(__file__).resolve().parents[1]


def input_bundle(repo):
    now, review, main, heartbeat, snapshot, proposal = fixture(repo)
    result = guard(repo, review, main, heartbeat, snapshot, deepcopy(snapshot), 'worker', 'run', proposal, at=now)
    files = result['bundle']['files'];proof = result['proof'];inputs = load_inputs(repo, review, main)
    return {'now': int(now.timestamp()*1000), 'snapshot': snapshot, 'confirmed': deepcopy(snapshot),
        'receipt': json.loads(files[proof['new_path']]),
        'before': {'manifest': inputs['manifests']['soups'], 'ledger': inputs['lifecycle'],
                   'stage': inputs['preflight_status'], 'policy': inputs['lifecycle_policy']},
        'after': {'manifest': json.loads(files['config/soups_review_manifest.json']),
                  'ledger': json.loads(files['config/content_review_candidate_lifecycle.json']),
                  'stage': json.loads(files['config/content_review_preflight_status.json'])}}


def invoke(value):
    code="""const {validateIntake}=require('./tools/content_review/soups_intake_site_guard.cjs');
let s='';process.stdin.on('data',x=>s+=x).on('end',()=>{try{const r=validateIntake(JSON.parse(s));
process.stdout.write(JSON.stringify(r));}catch(e){process.stderr.write(e.message);process.exitCode=1;}});"""
    return subprocess.run(['node','-e',code],cwd=ROOT,input=json.dumps(value,ensure_ascii=False),text=True,capture_output=True)


def test_site_guard_accepts_the_real_python_proposal_without_writing(tmp_path):
    value = input_bundle(tmp_path)
    result = invoke(value)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout) == {'status':'valid','candidate_count':1,'candidate_processing':False}


@pytest.mark.parametrize('change', ['decision','hash','history','stage','receipt','snapshot','number'])
def test_site_guard_rejects_changed_decisions_hashes_or_unrelated_state(tmp_path, change):
    value = input_bundle(tmp_path)
    row = value['after']['manifest']['records'][0]
    if change == 'decision': row['decision'] = 'approved'
    if change == 'hash': row['title'] = 'Changed reviewed content'
    if change == 'history': value['after']['ledger']['records']['soups:soups-new']['attempts'] = [{'outcome':'success'}]
    if change == 'stage': value['after']['stage']['records'][0]['checks']['duplicates'] = {'status':'passed'}
    if change == 'receipt': value['receipt']['publication_approved'] = True
    if change == 'snapshot': value['confirmed']['read_evidence']['jobs']['complete'] = False
    if change == 'number': row['reserved_review_number'] = 999
    result = invoke(value)
    assert result.returncode != 0


def test_site_guard_rejects_a_new_complete_review_decision(tmp_path):
    value = input_bundle(tmp_path)
    row = value['before']['manifest']['records'][0]
    snap = value['snapshot']
    snap['submissions'] = [{'id':'submission','user_id':'owner','collection':'soups','batch':1,'revision':1,
                            'accepted':0,'rejected':1,'payload_hash':'a'*64}]
    snap['decisions'] = [{'id':'decision','submission_id':'submission','user_id':'owner','collection':'soups',
                          'batch':1,'revision':1,'candidate_id':row['candidate_id'],'review_number':1,
                          'content_sha256':row['content_sha256'],'decision':'rejected'}]
    for key in ('submissions','decisions'):snap['read_evidence'][key]['rows_received']=1
    value['confirmed'] = deepcopy(snap)
    result = invoke(value)
    assert result.returncode != 0 and 'existing review state' in result.stderr

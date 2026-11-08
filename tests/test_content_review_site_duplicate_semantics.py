from copy import deepcopy
from datetime import timezone
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from tests.test_content_review_checkpoint_guard import fixture
from tests.test_content_review_duplicate_checkpoint import setup_bundle
from tools.content_review.verified_inputs import load_inputs

ROOT = Path(__file__).resolve().parents[1]


def bundle(repo):
    review, main, prepared = fixture(repo)
    inputs = load_inputs(repo, review, main)
    now, snapshot, *_ = setup_bundle()
    files = prepared['files']
    receipt = json.loads(files[prepared['new_paths_must_be_absent'][0]])
    # The old Python fixture predates the live Site lease requirement. Supply
    # the same acquired timestamp in both states, as a real lease does.
    inputs['worker_state']['lease']['acquired_at'] = receipt['checked_at']
    updated_state = json.loads(files['config/content_review_worker_status.json'])
    updated_state['lease']['acquired_at'] = receipt['checked_at']
    manifest = json.loads(files['config/weekly_review_manifest.json'])
    evidence = manifest['records'][0]['preflight']['checks']['duplicates']['evidence']
    identity = hashlib.sha256(('weekly\0fresh\0' + receipt['content_sha256']).encode()).hexdigest()
    return {'before': {'manifest': inputs['manifests']['weekly'], 'ledger': inputs['lifecycle'],
                       'stage': inputs['preflight_status'], 'state': inputs['worker_state'],
                       'policy': inputs['lifecycle_policy']},
            'after': {'manifest': manifest,
                      'ledger': json.loads(files['config/content_review_candidate_lifecycle.json']),
                      'stage': json.loads(files['config/content_review_preflight_status.json']),
                      'state': updated_state},
            'receipt': receipt, 'snapshot': snapshot, 'confirmed': deepcopy(snapshot),
            'expectedEvidence': evidence,
            'audit': {'status': 'clear', 'candidate_key_sha256': identity, 'review_commit': review,
                      'main_commit': main, 'input_blobs': deepcopy(evidence['input_blobs']), 'candidate_processing': False, 'candidate_writes': 0},
            'now': int(now.astimezone(timezone.utc).timestamp() * 1000)}


def invoke(value):
    code = """const {validateDuplicate}=require('./tools/content_review/site_duplicate_semantics.cjs');
let s='';process.stdin.on('data',x=>s+=x).on('end',()=>{try{process.stdout.write(JSON.stringify(validateDuplicate(JSON.parse(s))));}
catch(e){process.stderr.write(e.message);process.exitCode=1;}});"""
    return subprocess.run(['node', '-e', code], cwd=ROOT, input=json.dumps(value, ensure_ascii=False), text=True, capture_output=True)


def test_site_independently_validates_real_python_duplicate_bundle(tmp_path):
    value = bundle(tmp_path)
    result = invoke(value)
    assert result.returncode == 0, result.stderr
    checked = json.loads(result.stdout)
    assert checked['status'] == 'valid'
    assert checked['receipt_path'].endswith('.json')
    assert checked['candidate_processing'] is True
    assert checked['publication_verified'] is False


def test_reserved_soups_candidate_can_pass_duplicate_without_queue_promotion():
    from tools.content_review.duplicate_checkpoint import prepare
    now,snapshot,inputs,state,ledger=setup_bundle()
    inputs['registry'][0].update(id='soups',adapter='soups',manifest_url='https://example.test/config/soups_review_manifest.json')
    manifest=inputs['manifests'].pop('weekly');inputs['manifests']['soups']=manifest
    row=manifest['records'][0];row.pop('review_number');row.update(reserved_review_number=201,reserved_review_batch=11)
    entry=ledger['records'].pop('weekly:fresh');entry['collection']='soups';ledger['records']['soups:fresh']=entry
    inputs['lifecycle']=deepcopy(ledger);inputs['preflight_status']['records'][0]['collection']='soups'
    from tools.content_review.stage_summary import derive
    inputs['preflight_status']['summary']=derive(inputs['preflight_status']['records'])
    for proof in inputs['metadata']:
        if proof.get('path')=='config/weekly_review_manifest.json':proof['path']='config/soups_review_manifest.json'
    state['lease']['acquired_at']=now.isoformat();inputs['worker_state']=deepcopy(state)
    proposed=prepare(snapshot,deepcopy(snapshot),inputs,ledger,state,'worker','run','soups','fresh',
                     observed_heads={'review':'a'*40,'main':'b'*40},source_attempts={},source_progress={},at=now)
    files=proposed['files'];receipt=json.loads(files[proposed['new_paths_must_be_absent'][0]])
    after_manifest=json.loads(files['config/soups_review_manifest.json'])
    evidence=after_manifest['records'][0]['preflight']['checks']['duplicates']['evidence']
    checked={'before':{'manifest':manifest,'ledger':ledger,'stage':inputs['preflight_status'],'state':state,'policy':inputs['lifecycle_policy']},
             'after':{'manifest':after_manifest,'ledger':json.loads(files['config/content_review_candidate_lifecycle.json']),
                      'stage':json.loads(files['config/content_review_preflight_status.json']),
                      'state':json.loads(files['config/content_review_worker_status.json'])},
             'receipt':receipt,'snapshot':snapshot,'confirmed':deepcopy(snapshot),'expectedEvidence':evidence,
             'audit':{'status':'clear','candidate_key_sha256':hashlib.sha256(('soups\0fresh\0'+row['content_sha256']).encode()).hexdigest(),
                      'review_commit':'a'*40,'main_commit':'b'*40,'input_blobs':deepcopy(evidence['input_blobs']),
                      'candidate_processing':False,'candidate_writes':0},'now':int(now.timestamp()*1000)}
    result=invoke(checked);assert result.returncode==0,result.stderr
    assert 'review_number' not in after_manifest['records'][0]
    collision=deepcopy(checked)
    for side in ('before','after'):
        collision[side]['manifest']['records'].append({'candidate_id':'other','review_number':201})
    assert invoke(collision).returncode!=0
    reviewed=deepcopy(checked)
    for snap in (reviewed['snapshot'],reviewed['confirmed']):
        snap['submissions']=[{'id':'s','user_id':'owner','collection':'soups','batch':11,'revision':1,
                              'accepted':0,'rejected':1,'payload_hash':'a'*64}]
        snap['decisions']=[{'id':'d','submission_id':'s','user_id':'owner','collection':'soups','batch':11,'revision':1,
                            'candidate_id':'fresh','review_number':201,'content_sha256':row['content_sha256'],'decision':'rejected'}]
        for kind in ('submissions','decisions'):snap['read_evidence'][kind]['rows_received']=1
    assert invoke(reviewed).returncode!=0


def test_complete_unrelated_decision_and_job_are_preserved(tmp_path):
    value = bundle(tmp_path)
    for snap in (value['snapshot'], value['confirmed']):
        snap['submissions'] = [{'id':'s1','user_id':'owner','collection':'first','batch':1,'revision':1,
                                'accepted':1,'rejected':0,'payload_hash':'a'*64}]
        snap['decisions'] = [{'id':'d1','submission_id':'s1','user_id':'owner','collection':'first','batch':1,'revision':1,
                              'candidate_id':'another','review_number':1,'content_sha256':'b'*64,'decision':'approved'}]
        snap['jobs'] = [{'id':'j1','submission_id':'s1','user_id':'owner','collection':'first','revision':1,
                         'candidate_id':'another','content_sha256':'b'*64,'kind':'mechanical_assessment'}]
        for name in ('submissions', 'decisions', 'jobs'):
            snap['read_evidence'][name]['rows_received'] = 1
    result = invoke(value)
    assert result.returncode == 0, result.stderr
    value['snapshot']['jobs'][0]['content_sha256'] = 'c' * 64
    value['confirmed']['jobs'][0]['content_sha256'] = 'c' * 64
    assert invoke(value).returncode != 0


@pytest.mark.parametrize('change', ['decision', 'hash', 'stage', 'other_stage', 'history', 'attempt', 'state', 'progress',
                                    'receipt', 'snapshot', 'audit', 'candidate', 'evidence', 'submission'])
def test_site_rejects_unrelated_changes_or_unverified_evidence(tmp_path, change):
    value = bundle(tmp_path)
    if change == 'decision': value['after']['manifest']['records'][0]['decision'] = 'approved'
    if change == 'hash': value['after']['manifest']['records'][0]['title'] = 'Different content'
    if change == 'stage': value['after']['stage']['records'][0]['review_ready'] = True
    if change == 'other_stage': value['after']['stage']['records'].append({'candidate_id': 'another'})
    if change == 'history': value['after']['ledger']['records']['weekly:fresh']['history'] = []
    if change == 'attempt': value['after']['ledger']['records']['weekly:fresh']['attempts'][0]['outcome'] = 'unresolved'
    if change == 'state': value['after']['state']['lease']['owner'] = 'other'
    if change == 'progress': value['after']['state']['source_last_progress']['weekly'] = {'at': 'invented'}
    if change == 'receipt': value['receipt']['publication_approved'] = True
    if change == 'snapshot': value['confirmed']['read_evidence']['jobs']['complete'] = False
    if change == 'audit': value['audit']['status'] = 'held'
    if change == 'candidate': value['audit']['candidate_key_sha256'] = 'f' * 64
    if change == 'evidence': value['after']['manifest']['records'][0]['preflight']['checks']['duplicates']['evidence']['main_commit'] = 'f' * 40
    if change == 'submission':
        for snap in (value['snapshot'], value['confirmed']):
            snap['submissions'].append({'id': 'new', 'collection': 'weekly', 'batch': 1})
            snap['read_evidence']['submissions']['rows_received'] += 1
    assert invoke(value).returncode != 0

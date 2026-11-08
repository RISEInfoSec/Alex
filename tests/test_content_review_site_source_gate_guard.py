from copy import deepcopy
from datetime import timezone
import hashlib
import json
from pathlib import Path
import subprocess

import pytest
from tests.test_content_review_checkpoint_guard import fixture
from tests.test_content_review_duplicate_checkpoint import setup_bundle
from tests.test_content_review_verified_inputs import git, put
from tools.content_review.source_gate_checkpoint import prepare
from tools.content_review.verified_inputs import load_inputs, _path_blob

ROOT=Path(__file__).resolve().parents[1]


def bundle(repo):
    review,main,duplicate=fixture(repo)
    for path,content in duplicate['files'].items():put(repo,path,content)
    manifest=json.loads(duplicate['files']['config/weekly_review_manifest.json']);row=manifest['records'][0]
    source_path='config/content_review_source_receipts/'+'d'*64+'.json'
    row['source_processing']={'receipt':source_path,'retrieval_status':'retrieved','content_sha256':row['content_sha256']}
    put(repo,'config/weekly_review_manifest.json',manifest)
    state=json.loads(duplicate['files']['config/content_review_worker_status.json'])
    now,snapshot,*_=setup_bundle();state['lease']['acquired_at']=now.isoformat()
    put(repo,'config/content_review_worker_status.json',state)
    evidence={'requested_url':row['source_url'],'final_url':row['source_url'],'http_status':200,
              'retrieved_at':now.isoformat(),'body_sha256':'b'*64,'text':'Actual source text',
              'text_sha256':hashlib.sha256(b'Actual source text').hexdigest(),'container_type':'html','metadata':{}}
    item={'collection':'weekly','candidate_id':'fresh','content_sha256':row['content_sha256']}
    source={'independently_verified':True,'artifact_sha256':'c'*64,
            'request':{'request_id':'d'*64,'records':[{**item,'url':row['source_url']}]},
            'result':{'request_id':'d'*64,'status':'complete','read_only':True,
                      'records':[{**item,'status':'retrieved','evidence':[evidence]}]}}
    put(repo,source_path,source);git(repo,'add','.');git(repo,'commit','-qm','retained source')
    head=git(repo,'rev-parse','HEAD');inputs=load_inputs(repo,head,main)
    prepared=prepare(repo,snapshot,deepcopy(snapshot),inputs,inputs['lifecycle'],inputs['worker_state'],
        'worker','run','weekly','fresh','access',observed_heads={'review':head,'main':main},
        source_attempts=state['source_attempts'],source_progress=state['source_last_progress'],at=now)
    files=prepared['files'];receipt=json.loads(files[prepared['new_paths_must_be_absent'][0]])
    _,proof=_path_blob(repo,head,source_path)
    return {'before':{'manifest':inputs['manifests']['weekly'],'ledger':inputs['lifecycle'],
                      'stage':inputs['preflight_status'],'state':inputs['worker_state'],'policy':inputs['lifecycle_policy']},
            'after':{'manifest':json.loads(files['config/weekly_review_manifest.json']),
                     'ledger':json.loads(files['config/content_review_candidate_lifecycle.json']),
                     'stage':json.loads(files['config/content_review_preflight_status.json']),
                     'state':json.loads(files['config/content_review_worker_status.json'])},
            'receipt':receipt,'sourceReceipt':source,'sourceReceiptBlob':proof['blob_sha'],
            'snapshot':snapshot,'confirmed':deepcopy(snapshot),'now':int(now.astimezone(timezone.utc).timestamp()*1000)}


def invoke(value):
    script="const g=require('./tools/content_review/site_source_gate_guard.cjs');let s='';" \
           "process.stdin.on('data',x=>s+=x).on('end',()=>{try{process.stdout.write(JSON.stringify(g.validateSourceGate(JSON.parse(s))))}" \
           "catch(e){process.stderr.write(e.message);process.exitCode=1}});"
    return subprocess.run(['node','-e',script],cwd=ROOT,input=json.dumps(value),text=True,capture_output=True)


def test_site_independently_validates_actual_source_gate_proposal(tmp_path):
    result=invoke(bundle(tmp_path))
    assert result.returncode==0,result.stderr
    assert json.loads(result.stdout)['candidate_processing'] is True


def test_reserved_soups_candidate_can_pass_source_gate_without_queue_promotion(tmp_path):
    existing=bundle(tmp_path)
    def read(path):return json.loads((tmp_path/path).read_text())
    registry=read('config/review_console.json')
    item=next(x for x in registry['collections'] if x['id']=='weekly')
    item.update(id='soups',adapter='soups',manifest_url=item['manifest_url'].replace('weekly_review_manifest','soups_review_manifest'))
    manifest=read('config/weekly_review_manifest.json');row=manifest['records'][0]
    row.pop('review_number');row.update(reserved_review_number=201,reserved_review_batch=11)
    ledger=read('config/content_review_candidate_lifecycle.json')
    entry=ledger['records'].pop('weekly:fresh');entry['collection']='soups';ledger['records']['soups:fresh']=entry
    stage=read('config/content_review_preflight_status.json');stage['records'][0]['collection']='soups'
    from tools.content_review.stage_summary import derive
    stage['summary']=derive(stage['records'])
    state=read('config/content_review_worker_status.json')
    if 'weekly' in state.get('source_attempts',{}):state['source_attempts']['soups']=state['source_attempts'].pop('weekly')
    source_path=row['source_processing']['receipt'];source=read(source_path)
    source['request']['records'][0]['collection']='soups';source['result']['records'][0]['collection']='soups'
    for path,value in {'config/review_console.json':registry,'config/soups_review_manifest.json':manifest,
                       'config/content_review_candidate_lifecycle.json':ledger,'config/content_review_preflight_status.json':stage,
                       'config/content_review_worker_status.json':state,source_path:source}.items():put(tmp_path,path,value)
    git(tmp_path,'add','.');git(tmp_path,'commit','-qm','reserved soups source')
    head=git(tmp_path,'rev-parse','HEAD');main=existing['receipt']['source_main_commit'];inputs=load_inputs(tmp_path,head,main)
    now,snapshot,*_=setup_bundle()
    proposal=prepare(tmp_path,snapshot,deepcopy(snapshot),inputs,inputs['lifecycle'],inputs['worker_state'],'worker','run','soups','fresh','access',
                     observed_heads={'review':head,'main':main},source_attempts=state['source_attempts'],source_progress=state['source_last_progress'],at=now)
    files=proposal['files'];receipt=json.loads(files[proposal['new_paths_must_be_absent'][0]])
    _,proof=_path_blob(tmp_path,head,source_path)
    data={'before':{'manifest':inputs['manifests']['soups'],'ledger':inputs['lifecycle'],'stage':inputs['preflight_status'],
                    'state':inputs['worker_state'],'policy':inputs['lifecycle_policy']},
          'after':{'manifest':json.loads(files['config/soups_review_manifest.json']),
                   'ledger':json.loads(files['config/content_review_candidate_lifecycle.json']),
                   'stage':json.loads(files['config/content_review_preflight_status.json']),
                   'state':json.loads(files['config/content_review_worker_status.json'])},
          'receipt':receipt,'sourceReceipt':source,'sourceReceiptBlob':proof['blob_sha'],'snapshot':snapshot,
          'confirmed':deepcopy(snapshot),'now':int(now.timestamp()*1000)}
    result=invoke(data);assert result.returncode==0,result.stderr
    assert 'review_number' not in data['after']['manifest']['records'][0]
    collision=deepcopy(data)
    for side in ('before','after'):collision[side]['manifest']['records'].append({'candidate_id':'other','review_number':201})
    assert invoke(collision).returncode!=0
    reviewed=deepcopy(data)
    for snap in (reviewed['snapshot'],reviewed['confirmed']):
        snap['submissions']=[{'id':'s','user_id':'owner','collection':'soups','batch':11,'revision':1,
                              'accepted':0,'rejected':1,'payload_hash':'a'*64}]
        snap['decisions']=[{'id':'d','submission_id':'s','user_id':'owner','collection':'soups','batch':11,'revision':1,
                            'candidate_id':'fresh','review_number':201,'content_sha256':row['content_sha256'],'decision':'rejected'}]
        for kind in ('submissions','decisions'):snap['read_evidence'][kind]['rows_received']=1
    assert invoke(reviewed).returncode!=0


@pytest.mark.parametrize('change',['decision','hash','stage','history','state','progress','receipt','snapshot','evidence','source'])
def test_site_rejects_forged_source_gate_or_unrelated_changes(tmp_path,change):
    value=bundle(tmp_path)
    if change=='decision':value['after']['manifest']['records'][0]['decision']='approved'
    if change=='hash':value['after']['manifest']['records'][0]['title']='changed'
    if change=='stage':value['after']['stage']['records'][0]['review_ready']=True
    if change=='history':value['after']['ledger']['records']['weekly:fresh']['history']=[]
    if change=='state':value['after']['state']['lease']['owner']='other'
    if change=='progress':value['after']['state']['source_last_progress']['weekly']={'at':'invented'}
    if change=='receipt':value['receipt']['publication_approved']=True
    if change=='snapshot':value['confirmed']['read_evidence']['jobs']['complete']=False
    if change=='evidence':value['after']['manifest']['records'][0]['preflight']['checks']['access']['evidence']['body_sha256']='0'*64
    if change=='source':value['sourceReceipt']['result']['records'][0]['evidence'][0]['text']='tampered'
    assert invoke(value).returncode!=0

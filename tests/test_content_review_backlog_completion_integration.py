from copy import deepcopy
from datetime import timedelta
import json

from tests.test_content_review_duplicate_checkpoint import setup_bundle
from tests.test_content_review_unattended_simulation import commit_files
from tests.test_content_review_verified_inputs import fixture as input_fixture,git,put
from tests.test_content_review_site_run_complete_guard import invoke
from tools.content_review.checkpoint_guard import verify
from tools.content_review.duplicate_checkpoint import prepare as checkpoint
from tools.content_review.heartbeat_evidence import prepare as heartbeat
from tools.content_review.lease_transition import prepare as lease
from tools.content_review.lifecycle import evaluate
from tools.content_review.manifest_integrity import reviewed_digest
from tools.content_review.run_completion import prepare as complete
from tools.content_review.stage_summary import derive
from tools.content_review.verified_inputs import load_inputs


def two_fixture(tmp_path):
    now,snapshot,inputs,state,ledger=setup_bundle();first=inputs['manifests']['weekly']['records'][0]
    other=deepcopy(first);other.update(candidate_id='fresh-two',review_number=2,title='Independent unrelated study',
        source_url='https://example.test/distinct-paper');other['content_sha256']=reviewed_digest(other)
    inputs['manifests']['weekly']['records'].append(other)
    entry=evaluate(other,at=now);entry['collection']='weekly';ledger['records']['weekly:fresh-two']=entry
    records=inputs['preflight_status']['records'];records.append({'collection':'weekly','candidate_id':'fresh-two',
        'content_sha256':other['content_sha256'],'checks':deepcopy(other['preflight']['checks']),'status':'held','review_ready':False})
    inputs['preflight_status']['summary']=derive(records);state['lease']=None
    state['current_run']={'run_id':'old','application_status':'complete','receipt':'preserved'}
    _,main,_=input_fixture(tmp_path);target='Automation_worker1'
    for path,value in {'config/weekly_review_manifest.json':inputs['manifests']['weekly'],
      'config/content_review_candidate_lifecycle.json':ledger,'config/content_review_preflight_status.json':inputs['preflight_status'],
      'config/content_review_worker_status.json':state,'config/content_review_lifecycle_policy.json':inputs['lifecycle_policy'],
      'config/content_review_monitor_config.json':{'target_automation_id':target,'heartbeat_ref':'codex/content-review-heartbeat'}}.items():put(tmp_path,path,value)
    git(tmp_path,'add','.');git(tmp_path,'commit','-qm','two candidate fixture');head=git(tmp_path,'rev-parse','HEAD')
    native={'id':target,'is_enabled':True,'schedule':'BEGIN:VEVENT\nDTSTART:20261106T200000Z\nRRULE:FREQ=HOURLY\nEND:VEVENT',
        'run_details':{'last_run':{'id':'run','recorded_status':'in_progress','scheduled_for':now.isoformat(),'started_at':now.isoformat()}}}
    started=lease(tmp_path,head,native,'worker','run','start',at=now);head=commit_files(tmp_path,head,{started['path']:started['content']},'lease')
    paths=[];commits=[]
    for index,cid in enumerate(('fresh','fresh-two'),1):
        loaded=load_inputs(tmp_path,head,main);worker=loaded['worker_state'];lifecycle=loaded['lifecycle']
        bundle=checkpoint(snapshot,deepcopy(snapshot),loaded,lifecycle,worker,'worker','run','weekly',cid,
            observed_heads={'review':head,'main':main},source_attempts=worker.get('source_attempts',{}),
            source_progress=worker.get('source_last_progress',{}),at=now+timedelta(seconds=index*5))
        assert bundle['status']=='prepared';verify(tmp_path,head,main,bundle)
        paths.extend(bundle['new_paths_must_be_absent']);head=commit_files(tmp_path,head,bundle['files'],'checkpoint');commits.append(head)
    worker=json.loads(git(tmp_path,'show',head+':config/content_review_worker_status.json'))
    hb=heartbeat(worker,head,'worker','run',at=now+timedelta(seconds=15));branch=git(tmp_path,'symbolic-ref','--short','HEAD')
    git(tmp_path,'checkout','-qb','heartbeat');put(tmp_path,'config/content_review_detached_heartbeat.json',hb)
    git(tmp_path,'add','.');git(tmp_path,'commit','-qm','heartbeat');hbhead=git(tmp_path,'rev-parse','HEAD');git(tmp_path,'checkout','-q',branch)
    return now,head,main,hbhead,native,snapshot,paths,commits


def test_two_real_linear_checkpoints_produce_one_honest_independently_validated_receipt(tmp_path):
    now,head,main,hbhead,native,snapshot,paths,commits=two_fixture(tmp_path)
    worker=json.loads(git(tmp_path,'show',head+':config/content_review_worker_status.json'))
    proposed=complete(tmp_path,head,main,hbhead,native,snapshot,deepcopy(snapshot),'worker','run',paths,at=now+timedelta(seconds=15))
    receipt=json.loads(proposed['files'][proposed['new_path']]);after=json.loads(proposed['files']['config/content_review_worker_status.json'])
    assert len(receipt['completed_actions'])==2 and receipt['pilot']['attempted_candidate_ids']==['fresh','fresh-two']
    assert after['lease'] is None and receipt['native_completion_verified'] is False and receipt['publication_approved'] is False
    independent=invoke({'before':worker,'after':after,'receipt':receipt,'owner':'worker','runId':'run',
                        'verifiedActions':receipt['completed_actions'],'now':int((now.timestamp()+15)*1000)})
    assert independent.returncode==0,independent.stderr

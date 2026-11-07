"""Prepare a review-bound heartbeat for an independently updated Git ref."""
import hashlib
import json

from tools.content_review.heartbeat_evidence import prepare as prepare_record
from tools.content_review.verified_inputs import SHA, _git, _path_blob

PATH='config/content_review_detached_heartbeat.json'
WORKER='config/content_review_worker_status.json'
CONFIG='config/content_review_monitor_config.json'


def prepare(repo, review_head, heartbeat_head, owner, run_id, *, at=None):
    if not isinstance(heartbeat_head,str) or not SHA.fullmatch(heartbeat_head):
        raise ValueError('Immutable heartbeat branch head is required')
    state_raw,_=_path_blob(repo,review_head,WORKER)
    config_raw,_=_path_blob(repo,review_head,CONFIG)
    state,config=json.loads(state_raw),json.loads(config_raw)
    target=config.get('target_automation_id') if isinstance(config,dict) else None
    if not isinstance(state,dict) or not target or (state.get('current_run') or {}).get('scheduler',{}).get('id')!=target:
        raise ValueError('Configured worker does not match the current run')
    old_entry=_git(repo,'ls-tree','-z',heartbeat_head,'--',PATH)
    previous,base=None,None
    if old_entry:
        old,base=_path_blob(repo,heartbeat_head,PATH)
        previous=json.loads(old)
    record=prepare_record(state,review_head,owner,run_id,previous=previous,at=at)
    content=json.dumps(record,ensure_ascii=False,indent=2)+'\n'; raw=content.encode('utf-8')
    tree=_git(repo,'rev-parse',heartbeat_head+'^{tree}').decode('ascii').strip()
    if not SHA.fullmatch(tree):raise ValueError('Invalid heartbeat base tree')
    return {'path':PATH,'heartbeat_head':heartbeat_head,'review_head':review_head,'base_tree_sha':tree,
            'base_blob':base,'content':content,'blob_sha':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),
            'size':len(raw),'owner':owner,'run_id':run_id,'writes':0,
            'requires_expected_head_and_readback':True}

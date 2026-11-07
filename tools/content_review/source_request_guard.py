"""Validate an atomic source-request reservation without publishing it."""
from datetime import datetime,timezone
import hashlib
import json
import re

from tools.content_review.lifecycle import instant
from tools.content_review.source_plan import prepare as prepare_plan
from tools.content_review.verified_inputs import SHA,_git,_path_blob

WORKER='config/content_review_worker_status.json'


def prepare(repo,review_head,main_head,heartbeat_head,snapshot,confirmed,owner,run_id,proposal,*,at=None):
    now=at or datetime.now(timezone.utc)
    if not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Timezone-aware source reservation time required')
    if not all(isinstance(x,str) and SHA.fullmatch(x) for x in (review_head,main_head,heartbeat_head)):
        raise ValueError('Immutable source and heartbeat heads are required')
    if not isinstance(proposal,dict) or proposal.get('status')!='prepared' or proposal.get('writes')!=0:
        raise ValueError('Prepared source reservation is required')
    request=proposal.get('request') or {};reserved=proposal.get('reserved_state')
    pending=(reserved or {}).get('current_run',{}).get('pending_source_request') or {}
    prepared=instant(pending.get('prepared_at'))
    if not prepared or prepared>now or (now-prepared).total_seconds()>40:
        raise ValueError('Source reservation is stale or unavailable')
    raw,base=_path_blob(repo,review_head,WORKER);old=json.loads(raw)
    counts=(old.get('current_run') or {}).get('request_counts') or {}
    # Recompute the complete plan from committed inputs and the same private
    # snapshots, rather than trusting an arbitrary proposed request.
    expected=prepare_plan(repo,review_head,main_head,heartbeat_head,snapshot,confirmed,owner,run_id,
                          observed_heads={'review':review_head,'main':main_head},
                          source_requests_used=counts.get('source'),at=prepared)
    for key in ('status','request','reserved_state','held','coverage','d1_fingerprint_private'):
        if expected.get(key)!=proposal.get(key):raise ValueError('Source reservation differs from the verified plan')
    request_id=request.get('request_id')
    if not isinstance(request_id,str) or not re.fullmatch(r'[0-9a-f]{64}',request_id):
        raise ValueError('Invalid source request identity')
    path='config/content_review_source_requests/'+request_id+'.json'
    if _git(repo,'ls-tree','-z',review_head,'--',path):raise ValueError('Source request already exists; reconcile before retrying')
    files={WORKER:json.dumps(reserved,ensure_ascii=False,indent=2)+'\n',path:json.dumps(request,ensure_ascii=False,indent=2)+'\n'}
    blobs={}
    for name,content in files.items():
        value=content.encode('utf-8')
        if len(value)>32*1024*1024:raise ValueError('Source reservation exceeds bounded size')
        blobs[name]={'blob_sha':hashlib.sha1(b'blob '+str(len(value)).encode()+b'\0'+value).hexdigest(),
                     'size':len(value),'sha256':hashlib.sha256(value).hexdigest()}
    tree=_git(repo,'rev-parse',review_head+'^{tree}').decode('ascii').strip()
    if not SHA.fullmatch(tree):raise ValueError('Invalid review tree')
    private=proposal.get('d1_fingerprint_private')
    if not isinstance(private,str) or not re.fullmatch(r'[0-9a-f]{64}',private):raise ValueError('Private D1 fingerprint is unavailable')
    bundle={'status':'prepared','writes':0,'files':files,'d1_fingerprint_private':private}
    from tools.content_review.proposed_tree import bind_guarded
    expected_tree=bind_guarded(repo,review_head,files,{WORKER:base},path,blobs)
    proof={'kind':'source_request','expected_head':review_head,'expected_main':main_head,'base_tree_sha':tree,'expected_tree':expected_tree,
           'blobs':blobs,'base_blobs':{WORKER:base},'new_path':path,'heartbeat_head':heartbeat_head,
           'd1_fingerprint_private':private,'lease_owner':owner,'run_id':run_id,
           'requires_remote_head_d1_and_lease_recheck':True,'writes':0}
    return {'bundle':bundle,'proof':proof,'writes':0,'requires_atomic_update_and_readback':True}

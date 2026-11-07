"""Prepare a verified source receipt and usage update as one atomic bundle."""
from datetime import datetime,timezone
import hashlib
import json
import re

from tools.content_review.d1_reconcile import reconcile
from tools.content_review.heartbeat_evidence import verify as verify_heartbeat
from tools.content_review.source_accounting import prepare as account
from tools.content_review.verified_inputs import SHA,_git,_path_blob,load_inputs

WORKER='config/content_review_worker_status.json'


def prepare(repo,review_head,main_head,heartbeat_head,snapshot,confirmed,request_id,result_bytes,native_run,artifact,
            owner,run_id,*,observed_heads,at=None):
    now=at or datetime.now(timezone.utc)
    if not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('Timezone-aware source result time is required')
    if not all(isinstance(x,str) and SHA.fullmatch(x) for x in (review_head,main_head,heartbeat_head)):
        raise ValueError('Immutable source and heartbeat heads are required')
    if not isinstance(observed_heads,dict) or observed_heads.get('review')!=review_head or observed_heads.get('main')!=main_head:
        raise ValueError('Current source heads are unavailable or changed')
    if not isinstance(request_id,str) or not re.fullmatch(r'[0-9a-f]{64}',request_id):
        raise ValueError('Source request identity is invalid')
    inputs=load_inputs(repo,review_head,main_head);state=inputs['worker_state']
    beat_raw,_=_path_blob(repo,heartbeat_head,'config/content_review_detached_heartbeat.json')
    verify_heartbeat(json.loads(beat_raw),state,review_head,owner,run_id,at=now)
    request_raw,_=_path_blob(repo,review_head,'config/content_review_source_requests/'+request_id+'.json')
    request=json.loads(request_raw)
    accounted=account(state,request,result_bytes,native_run,artifact,owner,run_id,at=now)
    receipt_path='config/content_review_source_receipts/'+request_id+'.json'
    existing=_git(repo,'ls-tree','-z',review_head,'--',receipt_path)
    if accounted['status']=='already_accounted':
        if not existing:raise ValueError('Accounted source receipt is missing')
        prior,_=_path_blob(repo,review_head,receipt_path)
        if json.loads(prior)!=accounted['receipt']:raise ValueError('Existing source receipt differs from verified evidence')
        return {'status':'already_accounted','writes':0}
    if existing:raise ValueError('Source receipt already exists; reconcile before retrying')
    checked=reconcile(snapshot,confirmed,{k:v.get('records',[]) for k,v in inputs['reconciliation_manifests'].items()})
    files={WORKER:json.dumps(accounted['state'],ensure_ascii=False,indent=2)+'\n',
           receipt_path:json.dumps(accounted['receipt'],ensure_ascii=False,indent=2)+'\n'}
    blobs={}
    for name,content in files.items():
        raw=content.encode('utf-8')
        if len(raw)>32*1024*1024:raise ValueError('Source result bundle exceeds bounded size')
        blobs[name]={'blob_sha':hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest(),
                     'size':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    _,base=_path_blob(repo,review_head,WORKER)
    tree=_git(repo,'rev-parse',review_head+'^{tree}').decode('ascii').strip()
    if not SHA.fullmatch(tree):raise ValueError('Invalid review tree')
    private=checked['snapshot_sha256']
    bundle={'status':'prepared','writes':0,'files':files,'d1_fingerprint_private':private}
    proof={'kind':'source_result','expected_head':review_head,'expected_main':main_head,'base_tree_sha':tree,
           'blobs':blobs,'base_blobs':{WORKER:base},'new_path':receipt_path,'heartbeat_head':heartbeat_head,
           'd1_fingerprint_private':private,'lease_owner':owner,'run_id':run_id,
           'requires_remote_head_d1_and_lease_recheck':True,'writes':0}
    return {'status':'prepared','bundle':bundle,'proof':proof,'writes':0,'requires_atomic_update_and_readback':True}

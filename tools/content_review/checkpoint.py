"""Build atomic native-GitHub checkpoints without credentials or remote writes."""
import json
from datetime import datetime,timezone
from pathlib import Path
from tools.content_review.lifecycle import instant
from tools.content_review.manifest_integrity import validate_update
from tools.content_review.snapshot_integrity import verify_bytes

def prepare(root,paths,base_blobs,lease,owner,at=None):
    now=at or datetime.now(timezone.utc)
    if lease.get('owner')!=owner or not instant(lease.get('expires_at')) or instant(lease['expires_at'])<=now:
        raise ValueError('Checkpoint requires current matching unexpired lease')
    tree=[]
    for name in paths:
        p=Path(name)
        if p.is_absolute() or '..' in p.parts:raise ValueError('Repository-relative path required')
        after=(Path(root)/p).read_text()
        if name in base_blobs:
            old=base_blobs[name];verify_bytes(old['content'],old['sha'],old['size'])
            if name.endswith('_review_manifest.json'):validate_update(old['content'],after)
        tree.append({'path':name,'mode':'100644','type':'blob','content':after})
    return tree

def heartbeat(state,owner,run_id,at=None):
    stamp=(at or datetime.now(timezone.utc)).isoformat()
    if state.get('lease',{}).get('owner')!=owner:raise ValueError('Another lease owner')
    if state.get('current_run',{}).get('run_id')!=run_id:raise ValueError('Heartbeat run mismatch')
    state['last_heartbeat_at']=stamp;state['current_run']['observed_at']=stamp
    return state

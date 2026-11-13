"""Find the unique immutable source reservation in bounded Git history."""
import json
import re
from tools.content_review.source_result_guard import _verify_request_commit
from tools.content_review.verified_inputs import SHA,_git,_path_blob


def find(repo,review_head):
    if not isinstance(review_head,str) or not SHA.fullmatch(review_head):raise ValueError('Immutable review head required')
    raw,_=_path_blob(repo,review_head,'config/content_review_worker_status.json');state=json.loads(raw)
    pending=(state.get('current_run') or {}).get('pending_source_request') or {};rid=pending.get('request_id')
    if not isinstance(rid,str) or not re.fullmatch(r'[0-9a-f]{64}',rid):raise ValueError('Pending source request unavailable')
    path='config/content_review_source_requests/'+rid+'.json';request_raw,_=_path_blob(repo,review_head,path);request=json.loads(request_raw)
    cursor=review_head;found=None
    for _ in range(20):
        parts=_git(repo,'rev-list','--parents','-n','1',cursor).decode('ascii').split()
        if len(parts)!=2:raise ValueError('Source reservation is outside linear history')
        parent=parts[1]
        if not _git(repo,'ls-tree','-z',parent,'--',path):found=cursor;break
        cursor=parent
    if not found:raise ValueError('Source reservation is outside bounded history')
    _verify_request_commit(repo,review_head,path,request_raw,request,{'head_sha':found})
    return {'reservation_head':found,'request_id':rid}

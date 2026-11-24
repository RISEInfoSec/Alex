"""Read back a heartbeat whose original POST returned an uncertain result."""
from datetime import timezone
import json
from time import sleep
from urllib.request import Request, build_opener
from tools.content_review.github_read_objects import api
from tools.content_review.lifecycle import instant
from tools.content_review.site_reconcile_client import NoRedirect
from tools.content_review.verified_inputs import _path_blob, SHA

REVIEW='refs/heads/codex/soups-corpus-review'
MAIN='refs/heads/main'
HEARTBEAT='refs/heads/codex/content-review-heartbeat'
FENCE='https://alex-research-review.neil-schwartzm917549.chatgpt.site/api/content-review-migration-fence'


def fence_idle(token):
    req=Request(FENCE,headers={'OAI-Sites-Authorization':'Bearer '+token,'Accept':'application/json','Cache-Control':'no-cache'})
    with build_opener(NoRedirect).open(req,timeout=8) as response:
        body=response.read(65537)
        if response.status!=200 or len(body)>65536:
            return False
        fence=json.loads(body)
    return fence.get('status')=='idle' and fence.get('checkpoint_idle') is True


def confirm(repo, token, proposal, main, clock, heads, fetch, *, get=api, read=_path_blob, idle=fence_idle, wait=sleep):
    target=proposal['heartbeat_head']
    record=json.loads(proposal['content'])
    stamp=instant(record['observed_at'])
    expires=instant(record['lease_expires_at'])
    def fresh():
        now=clock().astimezone(timezone.utc)
        return stamp and expires and 0 <= (now-stamp).total_seconds() < 40 and now < expires
    for delay in (0,0.5,1.5,2.5):
        if delay:wait(delay)
        if not fresh():break
        refs=heads(repo)
        if refs.get(REVIEW)!=proposal['review_head'] or refs.get(MAIN)!=main:break
        new=refs.get(HEARTBEAT)
        if new==target:continue
        if not SHA.fullmatch(new or ''):break
        commit=get('/commits/'+new)
        if (commit.get('sha')!=new or [p['sha'] for p in commit.get('parents',[])]!=[target]
                or [(f['filename'],f['sha']) for f in commit.get('files',[])]!=[(proposal['path'],proposal['blob_sha'])]):
            break
        fetch(repo,refs,record['run_id'])
        raw,meta=read(repo,new,proposal['path'])
        if raw!=proposal['content'].encode() or meta.get('blob_sha')!=proposal['blob_sha']:break
        if not idle(token) or heads(repo)!=refs or not fresh():break
        return {'status':'committed_and_read_back','action':'heartbeat','commit_sha':new}
    raise ValueError('Heartbeat outcome unconfirmed; reconcile ref')

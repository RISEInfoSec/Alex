"""Bounded detached heartbeat transport for the hourly coordinator.

Uses the private Site's existing writer. The service token remains in memory;
Git ref reads are restricted to the public repository and carry no token.
"""
from datetime import datetime, timezone
import errno
import json
from pathlib import Path
import re
import subprocess

from tools.content_review.coordinator_heartbeat import HeartbeatKeeper
from tools.content_review.detached_heartbeat import prepare
from tools.content_review.site_worker_client import post
from tools.content_review.verified_inputs import SHA, _path_blob

REVIEW='refs/heads/codex/soups-corpus-review'
MAIN='refs/heads/main'
HEARTBEAT='refs/heads/codex/content-review-heartbeat'
REFS=(REVIEW,MAIN,HEARTBEAT)
ID=re.compile(r'^[a-zA-Z0-9-]{1,100}$')
GIT_OPERATIONS=('remote','ls_remote','fetch','cat_file','other')
GIT_FAILURES=('timed_out','resource_unavailable','access_denied','rate_limited','network_unavailable','failed')
SAFE_GIT_ERRORS=frozenset('Coordinator Git '+op+' '+reason for op in GIT_OPERATIONS for reason in GIT_FAILURES)


def _run(repo,*args,input_text=None):
    operation={'remote':'remote','ls-remote':'ls_remote','fetch':'fetch','cat-file':'cat_file'}.get(args[0] if args else '', 'other')
    try:
        return subprocess.run(['git','-C',str(repo),*args],input=input_text,check=True,capture_output=True,text=True,timeout=45).stdout.strip()
    except (OSError,subprocess.SubprocessError) as exc:
        reason='failed'
        if isinstance(exc,subprocess.TimeoutExpired):reason='timed_out'
        elif isinstance(exc,OSError) and exc.errno in (errno.EAGAIN,errno.ENOMEM,errno.EMFILE,errno.ENFILE):reason='resource_unavailable'
        elif isinstance(exc,subprocess.CalledProcessError):
            stderr=exc.stderr if isinstance(exc.stderr,str) else ''
            text=stderr.lower()
            if any(x in text for x in ('cannot fork','unable to fork','fork failed','resource temporarily unavailable','unable to create thread')):
                reason='resource_unavailable'
            elif '429' in text or 'rate limit' in text:reason='rate_limited'
            elif any(x in text for x in ('authentication failed','permission denied','could not read username','403 forbidden','error: 403')):
                reason='access_denied'
            elif any(x in text for x in ('could not resolve','failed to connect','network is unreachable','connection timed out','connection refused','proxy error')):
                reason='network_unavailable'
        raise ValueError('Coordinator Git '+operation+' '+reason) from exc


def _missing_commits(repo,shas):
    """Inspect only exact commit IDs; reject unexpected or incomplete Git output."""
    ordered=list(dict.fromkeys(shas))
    output=_run(repo,'cat-file','--batch-check=%(objectname) %(objecttype)',input_text=''.join(x+'^{commit}\n' for x in ordered))
    lines=output.splitlines()
    if len(lines)!=len(ordered):raise ValueError('Coordinator Git object verification failed')
    missing=[]
    for sha,line in zip(ordered,lines):
        if line==sha+' commit':continue
        if line==sha+'^{commit} missing':missing.append(sha);continue
        raise ValueError('Coordinator Git object verification failed')
    return missing


def _check_remote(repo):
    value=_run(repo,'remote','get-url','origin')
    if value not in ('https://github.com/RISEInfoSec/Alex','https://github.com/RISEInfoSec/Alex.git'):
        raise ValueError('Coordinator repository remote differs')


def read_heads(repo):
    _check_remote(repo)
    result={}
    for line in _run(repo,'ls-remote','origin',*REFS).splitlines():
        parts=line.split('\t')
        if len(parts)!=2 or parts[1] not in REFS or parts[1] in result or not SHA.fullmatch(parts[0]):
            raise ValueError('Coordinator remote refs invalid')
        result[parts[1]]=parts[0]
    if set(result)!=set(REFS):raise ValueError('Coordinator remote refs incomplete')
    return result


def fetch_heads(repo,heads,run_id):
    if (not isinstance(run_id,str) or not ID.fullmatch(run_id) or not isinstance(heads,dict)
        or set(heads)!=set(REFS) or any(not isinstance(heads[ref],str) or not SHA.fullmatch(heads[ref]) for ref in REFS)):
        raise ValueError('Invalid coordinator fetch')
    _check_remote(repo)
    # Reuse verified local commit objects. Fetch only missing immutable IDs,
    # never moving refs or shared destination refs. This avoids repeatedly
    # transferring already-present history during heartbeat and foreground work.
    shas=list(dict.fromkeys(heads[ref] for ref in REFS));missing=_missing_commits(repo,shas)
    # Exact objects fetched without destination refs may otherwise be omitted
    # from Git's negotiation. Advertise only the already-verified local commits
    # as tips, so a new lease or heartbeat does not redownload old history.
    present=[sha for sha in shas if sha not in missing]
    if missing:_run(repo,'fetch','--no-tags','--no-write-fetch-head',
                    *('--negotiation-tip='+sha for sha in present),'origin',*missing)
    if _missing_commits(repo,shas):raise ValueError('Coordinator Git object verification failed')


class DetachedHeartbeatPulse:
    def __init__(self,repo,token,review_head,main_head,owner,run_id,*,heads=read_heads,fetch=fetch_heads,send=post,clock=None):
        if not isinstance(token,str) or not token or '\n' in token or '\r' in token or not SHA.fullmatch(review_head or '') or not SHA.fullmatch(main_head or ''):
            raise ValueError('Invalid coordinator heartbeat input')
        if not ID.fullmatch(owner or '') or not ID.fullmatch(run_id or '') or not all(callable(f) for f in (heads,fetch,send)):
            raise ValueError('Invalid coordinator heartbeat identity')
        self.repo=Path(repo);self._token=token;self.review=review_head;self.main=main_head;self.owner=owner;self.run=run_id
        self._heads=heads;self._fetch=fetch;self._send=send;self._clock=clock or (lambda:datetime.now(timezone.utc))

    def __call__(self):
        before=self._heads(self.repo)
        if before.get(REVIEW)!=self.review or before.get(MAIN)!=self.main:raise ValueError('Coordinator source heads changed')
        self._fetch(self.repo,before,self.run)
        proposal=prepare(self.repo,self.review,before[HEARTBEAT],self.owner,self.run,at=self._clock())
        result=self._send('heartbeat',{'proposal':proposal},self._token)
        if not isinstance(result,dict) or result.get('status')!='committed_and_read_back' or not SHA.fullmatch(result.get('commit_sha') or ''):
            raise ValueError('Heartbeat outcome unconfirmed; reconcile ref')
        after=self._heads(self.repo)
        if after.get(REVIEW)!=self.review or after.get(MAIN)!=self.main or after.get(HEARTBEAT)!=result['commit_sha']:
            raise ValueError('Heartbeat ref or source heads changed')
        self._fetch(self.repo,after,self.run)
        raw,meta=_path_blob(self.repo,after[HEARTBEAT],proposal['path'])
        if meta.get('blob_sha')!=proposal['blob_sha'] or raw.decode('utf-8')!=proposal['content']:
            raise ValueError('Heartbeat readback differs')
        # No token, native scheduler claim, private decision or source payload is returned.
        return {'status':'committed_and_read_back','commit_sha':after[HEARTBEAT]}


def maintain(repo,token,review_head,main_head,owner,run_id,**kwargs):
    """Immediately renew, then refresh at 12 seconds while bounded work runs."""
    return HeartbeatKeeper(DetachedHeartbeatPulse(repo,token,review_head,main_head,owner,run_id,**kwargs))

"""Bounded, single-writer FIRST/M3AAWG duplicate backlog pass.

The caller supplies a real native observation. Each confirmed checkpoint uses
the existing independent Site audit and D1 fence, sequentially under one lease.
No source, OpenAlex, paid or publication request is made. A deferred/ambiguous
write never becomes a success receipt. Existing held duplicate candidates are
not altered; recording their holds requires a separate independently checked path.
"""
from datetime import datetime,timezone
import re

from tools.content_review.coordinator_duplicate import checkpoint_one
from tools.content_review.coordinator_lifecycle import start,complete
from tools.content_review.backlog_identity_precheck import inspect as identity_precheck
from tools.content_review.lifecycle import instant
from tools.content_review.verified_inputs import SHA

TARGETS=('m3aawg','first')
CHECKPOINT=re.compile(r'^config/content_review_mechanical_checkpoints/[0-9a-f]{64}\.json$')
LIMIT=5


def _matching_native_runs(value,run_id):
    found=[]
    if isinstance(value,dict):
        if value.get('id')==run_id and value.get('recorded_status')=='in_progress' and 'started_at' in value and 'scheduled_for' in value:
            found.append(value)
        for item in value.values():found.extend(_matching_native_runs(item,run_id))
    elif isinstance(value,list):
        for item in value:found.extend(_matching_native_runs(item,run_id))
    return found


def run(repo,token,native,owner,run_id,*,begin=start,checkpoint=checkpoint_one,finish=complete,clock=None):
    clock=clock or (lambda:datetime.now(timezone.utc))
    now=clock();matches=_matching_native_runs(native,run_id)
    if not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset() is None or len(matches)!=1:
        raise ValueError('Matching native backlog observation required')
    started=instant(matches[0].get('started_at'))
    if not started or not 0<=(now-started).total_seconds()<240:
        return {'status':'blocked','reason':'insufficient_backlog_work_window','candidate_processing':False,
                'lease_release_confirmed':False,'reconcile_before_retry':False,'native_completion_verified':False}
    acquired=begin(repo,token,native,owner,run_id)
    if not isinstance(acquired,dict):raise ValueError('Backlog lease result invalid')
    if acquired.get('status')!='lease_started':return acquired
    review,main=acquired.get('review_head'),acquired.get('main_head')
    if not isinstance(review,str) or not SHA.fullmatch(review) or not isinstance(main,str) or not SHA.fullmatch(main):
        raise ValueError('Backlog source heads invalid')
    commits={};blocked=set();examined=[];turn=0
    while len(examined)<LIMIT and len(blocked)<len(TARGETS):
        now=clock()
        if not isinstance(now,datetime) or now.tzinfo is None or now.utcoffset() is None:raise ValueError('Backlog clock invalid')
        remaining=600-(now-started).total_seconds()
        # Reserve time for final re-audit of every committed action. The first
        # checkpoint has a larger start reserve so slow I/O does not consume the
        # entire native window before completion can begin.
        reserve=240+60*max(0,len(commits)-1)
        if remaining<reserve+120:break
        target=next((TARGETS[(turn+i)%len(TARGETS)] for i in range(len(TARGETS)) if TARGETS[(turn+i)%len(TARGETS)] not in blocked),None)
        if target is None:break
        turn=(TARGETS.index(target)+1)%len(TARGETS)
        # A held FIRST candidate must not use the M3AAWG pilot's whole budget.
        budget=LIMIT-len(examined)
        if target=='first' and 'm3aawg' not in blocked:budget=1
        result=checkpoint(repo,token,review,main,owner,run_id,only_collections=(target,),max_candidates=budget,
                          excluded_candidates=examined,precheck=identity_precheck,return_examined=True)
        if not isinstance(result,dict):raise ValueError('Backlog checkpoint response invalid')
        attempted=result.get('_examined_private')
        if (not isinstance(attempted,list) or len(attempted)>budget or any(
            not isinstance(x,(tuple,list)) or len(x)!=2 or x[0]!=target or not isinstance(x[1],str) or not x[1] for x in attempted)):
            raise ValueError('Backlog examined inventory invalid')
        additions=[tuple(x) for x in attempted]
        if len(set(additions))!=len(additions) or set(additions)&set(examined):raise ValueError('Backlog examined identity repeated')
        examined.extend(additions)
        status=result.get('status')
        if status=='blocked':
            return {'status':'blocked','reason':'backlog_checkpoint_unconfirmed','confirmed_checkpoint_count':len(commits),
                    'candidate_processing':True if commits else None,'lease_release_confirmed':False,
                    'reconcile_before_retry':True,'native_completion_verified':False,'publication_verified':False}
        if status=='deferred':
            reason=result.get('reason')
            if reason not in ('no_selected_duplicate_gate','duplicate_gate_held'):
                raise ValueError('Backlog deferral invalid')
            blocked.add(target);continue
        if status!='checkpoint_confirmed_run_incomplete':raise ValueError('Backlog checkpoint outcome invalid')
        commit,path=result.get('commit_sha'),result.get('receipt_path')
        if (not isinstance(commit,str) or not SHA.fullmatch(commit) or commit==review or not isinstance(path,str) or
            not CHECKPOINT.fullmatch(path) or path in commits or result.get('candidate_processing') is not True):
            raise ValueError('Backlog checkpoint identity invalid; reconcile before retrying')
        if not additions:raise ValueError('Backlog checkpoint had no examined candidate')
        commits[path]=commit;review=commit
    remaining=600-(clock()-started).total_seconds()
    if remaining<240+60*max(0,len(commits)-1):
        return {'status':'blocked','reason':'insufficient_time_to_verify_completion','confirmed_checkpoint_count':len(commits),
                'candidate_processing':bool(commits),'lease_release_confirmed':False,'reconcile_before_retry':True,
                'native_completion_verified':False,'publication_verified':False}
    result=finish(repo,token,native,review,main,owner,run_id,list(commits) if commits else None,
                  checkpoint_commits=commits)
    if not isinstance(result,dict):raise ValueError('Backlog completion outcome invalid')
    # Preserve the completion's verified status and avoid exposing private IDs.
    return {**result,'confirmed_checkpoint_count':len(commits),'backlog_candidate_ceiling':LIMIT}

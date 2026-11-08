"""Compose one bounded review pass; do not install or enable a scheduler.

The caller must supply a fresh native connector observation and arrange native
terminal verification after return. Duplicate and source-evidence paths are connected; remaining gates and
collection adapters still prevent treating this as a complete worker.
"""
from tools.content_review.coordinator_duplicate import checkpoint_one
from tools.content_review.coordinator_lifecycle import start, complete
from tools.content_review.coordinator_source_cycle import source_pass,_state
from tools.content_review.coordinator_heartbeat_transport import read_heads,fetch_heads,REVIEW,MAIN


def has_pending_source(repo,review_head,main_head,run_id,*,heads=read_heads,fetch=fetch_heads,state_reader=_state):
    refs=heads(repo)
    if refs.get(REVIEW)!=review_head or refs.get(MAIN)!=main_head:raise ValueError('Coordinator source heads changed')
    fetch(repo,refs,run_id)
    return state_reader(repo,review_head)['current_run'].get('pending_source_request') is not None


def mechanical_pass(repo,token,native,owner,run_id,*,begin=start,checkpoint=checkpoint_one,finish=complete,
                    pending_checker=has_pending_source,source_runner=source_pass):
    started=begin(repo,token,native,owner,run_id)
    if started.get('status')!='lease_started':return started
    review,main=started['review_head'],started['main_head']
    if pending_checker(repo,review,main,run_id):
        return source_runner(repo,token,native,review,main,owner,run_id)
    checked=checkpoint(repo,token,review,main,owner,run_id)
    if checked.get('status')=='blocked':return checked
    if checked.get('status')=='deferred':
        return source_runner(repo,token,native,review,main,owner,run_id)
    if checked.get('status')!='checkpoint_confirmed_run_incomplete':
        raise ValueError('Unrecognized checkpoint outcome; reconcile before retrying')
    return finish(repo,token,native,checked['commit_sha'],main,owner,run_id,checked['receipt_path'])

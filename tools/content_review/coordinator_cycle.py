"""Compose one mechanical-only pass; do not install or enable a scheduler.

The caller must supply a fresh native connector observation and arrange native
terminal verification after return. Other collection and gate paths remain
separate: this scope is not a complete replacement worker.
"""
from tools.content_review.coordinator_duplicate import checkpoint_one
from tools.content_review.coordinator_lifecycle import start, complete


def mechanical_pass(repo,token,native,owner,run_id,*,begin=start,checkpoint=checkpoint_one,finish=complete):
    started=begin(repo,token,native,owner,run_id)
    if started.get('status')!='lease_started':return started
    review,main=started['review_head'],started['main_head']
    checked=checkpoint(repo,token,review,main,owner,run_id)
    if checked.get('status')=='blocked':return checked
    if checked.get('status')=='deferred':
        result=finish(repo,token,native,review,main,owner,run_id,None)
        if result.get('status')=='deferred':result['reason']='no_supported_duplicate_checkpoint'
        return result
    if checked.get('status')!='checkpoint_confirmed_run_incomplete':
        raise ValueError('Unrecognized checkpoint outcome; reconcile before retrying')
    return finish(repo,token,native,checked['commit_sha'],main,owner,run_id,checked['receipt_path'])

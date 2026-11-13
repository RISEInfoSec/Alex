"""A controlled duplicate-only pass, with no source or paid requests.

This narrow test does not establish that the full review worker is deployed.
It uses the same lease, independently validated checkpoint and fenced release
as the replacement.  Any uncertain write must be reconciled before another run.
"""
import json

from tools.content_review.coordinator_duplicate import checkpoint_one
from tools.content_review.coordinator_lifecycle import start, complete
from tools.content_review.coordinator_heartbeat_transport import read_heads, fetch_heads, REVIEW, MAIN
from tools.content_review.verified_inputs import _path_blob


def has_pending_source(repo, review_head, main_head, run_id, *, heads=read_heads, fetch=fetch_heads):
    refs = heads(repo)
    if refs.get(REVIEW) != review_head or refs.get(MAIN) != main_head:
        raise ValueError('Pilot source heads changed')
    fetch(repo, refs, run_id)
    raw, _ = _path_blob(repo, review_head, 'config/content_review_worker_status.json')
    state = json.loads(raw)
    if not isinstance(state, dict) or not isinstance(state.get('current_run'), dict):
        raise ValueError('Pilot worker state unavailable')
    return state['current_run'].get('pending_source_request') is not None


def run(repo, token, native, owner, run_id, *, heads=read_heads, begin=start, pending_checker=has_pending_source,
        checkpoint=checkpoint_one, finish=complete):
    initial = heads(repo)
    if pending_checker(repo, initial[REVIEW], initial[MAIN], run_id):
        return {'status': 'blocked', 'reason': 'pending_source_requires_full_coordinator',
                'candidate_processing': False, 'native_completion_verified': False,
                'lease_release_confirmed': False}
    started = begin(repo, token, native, owner, run_id)
    if started.get('status') != 'lease_started':
        return started
    review, main = started['review_head'], started['main_head']
    if pending_checker(repo, review, main, run_id):
        # An unexpected race is not eligible for a no-work receipt. Keep the
        # source reservation and the lease intact for explicit reconciliation.
        return {'status': 'blocked', 'reason': 'pending_source_changed_after_lease',
                'candidate_processing': False, 'reconcile_before_retry': True,
                'native_completion_verified': False, 'lease_release_confirmed': False}
    checked = checkpoint(repo, token, review, main, owner, run_id)
    if checked.get('status') == 'blocked':
        return checked
    if checked.get('status') == 'deferred':
        return finish(repo, token, native, review, main, owner, run_id, None)
    if checked.get('status') != 'checkpoint_confirmed_run_incomplete':
        raise ValueError('Unrecognized pilot checkpoint; reconcile before retrying')
    return finish(repo, token, native, checked['commit_sha'], main, owner, run_id, checked['receipt_path'])

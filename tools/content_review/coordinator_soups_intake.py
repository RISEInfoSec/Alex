"""Prepare and checkpoint a bounded SOUPS intake under the live lease.

Intake only reserves identifiers and creates preflight/lifecycle entries. It
does not pass a review gate, establish candidate processing, or publish.
"""
from datetime import datetime, timezone
import json
import re

from tools.content_review.coordinator_heartbeat import HeartbeatKeeper
from tools.content_review.coordinator_heartbeat_transport import DetachedHeartbeatPulse, read_heads, fetch_heads, REVIEW, MAIN, HEARTBEAT
from tools.content_review.site_reconcile_client import read_snapshot
from tools.content_review.site_worker_client import post
from tools.content_review.soups_intake import prepare as plan_intake
from tools.content_review.soups_intake_guard import prepare as guard_intake
from tools.content_review.verified_inputs import SHA, _path_blob, load_inputs

ID = re.compile(r'^[a-zA-Z0-9-]{1,100}$')
RECEIPT = re.compile(r'^config/content_review_intake_receipts/[0-9a-f]{64}\.json$')


def intake(repo, token, review_head, main_head, owner, run_id, *, heads=read_heads, fetch=fetch_heads,
           snapshot_reader=read_snapshot, inputs_reader=load_inputs, pulse_factory=DetachedHeartbeatPulse,
           keeper_factory=HeartbeatKeeper, planner=plan_intake, guard=guard_intake, send=post, clock=None):
    if not SHA.fullmatch(review_head or '') or not SHA.fullmatch(main_head or '') or not ID.fullmatch(owner or '') or not ID.fullmatch(run_id or ''):
        raise ValueError('Invalid intake identity or source heads')
    if not isinstance(token, str) or not token or '\n' in token or '\r' in token:
        raise ValueError('Site intake access unavailable')
    clock = clock or (lambda: datetime.now(timezone.utc))
    pulse = pulse_factory(repo, token, review_head, main_head, owner, run_id)
    with keeper_factory(pulse) as keeper:
        refs = heads(repo)
        if refs.get(REVIEW) != review_head or refs.get(MAIN) != main_head:
            raise ValueError('Intake source heads changed')
        fetch(repo, refs, run_id)
        inputs = inputs_reader(repo, review_head, main_head)
        snapshot, confirmed = snapshot_reader(token)
        refs = heads(repo)
        if refs.get(REVIEW) != review_head or refs.get(MAIN) != main_head:
            raise ValueError('Intake source heads changed during snapshot')
        fetch(repo, refs, run_id)
        heartbeat_raw, _ = _path_blob(repo, refs[HEARTBEAT], 'config/content_review_detached_heartbeat.json')
        heartbeat = json.loads(heartbeat_raw)
        state, ledger = inputs['worker_state'], inputs['lifecycle']
        proposal = planner(snapshot, confirmed, inputs, ledger, state, owner, run_id,
                           observed_heads={'review': review_head, 'main': main_head},
                           source_attempts=state.get('source_attempts', {}),
                           source_progress=state.get('source_last_progress', {}), heartbeat=heartbeat, at=clock())
        if proposal.get('status') == 'no_soups_intake_due':
            keeper.check()
            return {'status': 'deferred', 'reason': 'no_soups_intake_due', 'candidate_processing': False}
        checked = guard(repo, review_head, main_head, refs[HEARTBEAT], snapshot, confirmed, owner, run_id, proposal, at=clock())
        keeper.check()
    bundle = checked.get('bundle') if isinstance(checked, dict) else None
    if not isinstance(bundle, dict) or bundle.get('status') != 'prepared' or bundle.get('writes') != 0 or not isinstance(bundle.get('files'), dict):
        raise ValueError('Guarded SOUPS intake proposal unavailable')
    refs = heads(repo)
    if refs.get(REVIEW) != review_head or refs.get(MAIN) != main_head:
        raise ValueError('Intake source heads changed')
    response = send('soups_intake', {'expectedHead': review_head, 'expectedMain': main_head,
                                    'owner': owner, 'runId': run_id, 'files': bundle['files']}, token)
    if not isinstance(response, dict) or response.get('status') != 'committed_and_read_back':
        return {'status': 'blocked', 'reason': 'soups_intake_unconfirmed', 'reconcile_before_retry': True,
                'candidate_processing': False, 'publication_verified': False}
    commit, receipt, count = response.get('commit_sha'), response.get('receipt_path'), response.get('candidate_count')
    if (not SHA.fullmatch(commit or '') or not isinstance(receipt, str) or not RECEIPT.fullmatch(receipt)
            or type(count) is not int or not 1 <= count <= 5 or response.get('candidate_processing') is not False
            or response.get('publication_verified') is not False):
        raise ValueError('Intake response is unconfirmed; reconcile before retrying')
    refs = heads(repo)
    if refs.get(REVIEW) != commit or refs.get(MAIN) != main_head:
        raise ValueError('Intake head changed; reconcile before retrying')
    try:
        bound = pulse_factory(repo, token, commit, main_head, owner, run_id)()
    except Exception:
        bound = None
    if not isinstance(bound, dict) or bound.get('status') != 'committed_and_read_back' or not SHA.fullmatch(bound.get('commit_sha') or ''):
        return {'status': 'blocked', 'reason': 'soups_intake_heartbeat_unconfirmed', 'commit_sha': commit,
                'reconcile_before_retry': True, 'candidate_processing': False, 'publication_verified': False}
    return {'status': 'intake_confirmed', 'commit_sha': commit, 'receipt_path': receipt,
            'candidate_count': count, 'heartbeat_rebound': True,
            'candidate_processing': False, 'publication_verified': False}

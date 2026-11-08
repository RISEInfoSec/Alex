"""Checkpoint one retained-source gate under a live lease, without release.

This is not a scheduler or publication route. Completion must independently
verify the source checkpoint before recording and releasing the run.
"""
from datetime import datetime, timezone
import json
import re

from tools.content_review.coordinator import plan
from tools.content_review.coordinator_heartbeat import HeartbeatKeeper
from tools.content_review.coordinator_heartbeat_transport import DetachedHeartbeatPulse, read_heads, fetch_heads, REVIEW, MAIN, HEARTBEAT
from tools.content_review.lifecycle import current_pass
from tools.content_review.site_reconcile_client import read_snapshot
from tools.content_review.site_worker_client import post
from tools.content_review.source_gate_checkpoint import prepare
from tools.content_review.verified_inputs import SHA, _path_blob, load_inputs

ID = re.compile(r'^[a-zA-Z0-9-]{1,100}$')
RECEIPT = re.compile(r'^config/content_review_source_gate_checkpoints/[0-9a-f]{64}\.json$')


def checkpoint_one(repo, token, review_head, main_head, owner, run_id, *, heads=read_heads, fetch=fetch_heads,
                   inputs_reader=load_inputs, snapshot_reader=read_snapshot, pulse_factory=DetachedHeartbeatPulse,
                   keeper_factory=HeartbeatKeeper, planner=plan, preparer=prepare, send=post, clock=None):
    if not SHA.fullmatch(review_head or '') or not SHA.fullmatch(main_head or '') or not ID.fullmatch(owner or '') or not ID.fullmatch(run_id or ''):
        raise ValueError('Invalid source gate identity or source heads')
    if not isinstance(token, str) or not token or '\n' in token or '\r' in token:
        raise ValueError('Site source gate access unavailable')
    clock = clock or (lambda: datetime.now(timezone.utc))
    pulse = pulse_factory(repo, token, review_head, main_head, owner, run_id)
    with keeper_factory(pulse) as keeper:
        refs = heads(repo)
        if refs.get(REVIEW) != review_head or refs.get(MAIN) != main_head:
            raise ValueError('Source gate heads changed')
        fetch(repo, refs, run_id)
        inputs = inputs_reader(repo, review_head, main_head)
        snapshot, confirmed = snapshot_reader(token)
        keeper.refresh()
        refs = heads(repo)
        if refs.get(REVIEW) != review_head or refs.get(MAIN) != main_head:
            raise ValueError('Source gate heads changed during snapshot')
        fetch(repo, refs, run_id)
        raw, _ = _path_blob(repo, refs[HEARTBEAT], 'config/content_review_detached_heartbeat.json')
        heartbeat = json.loads(raw)
        state, ledger = inputs['worker_state'], inputs['lifecycle']
        attempts, progress = state.get('source_attempts', {}), state.get('source_last_progress', {})
        selection = planner(snapshot, confirmed, inputs['reconciliation_manifests'], ledger, inputs['registry'], state, owner, run_id,
                            source_attempts=attempts, source_progress=progress, at=clock(), heartbeat=heartbeat, review_head=review_head,
                            stages=('source','metadata'),retained_source_only=True)
        candidates = [x for x in selection['selected'] if x.get('next_stage') in ('source', 'metadata')]
        proposal = None
        chosen_gate = None
        for item in candidates:
            manifest = inputs['manifests'].get(item['collection']) or {}
            rows = manifest.get('records', []) + manifest.get('preflight_records', [])
            matches = [x for x in rows if x.get('candidate_id') == item['candidate_id']]
            if len(matches) != 1:
                raise ValueError('Source gate candidate is ambiguous')
            for gate in ('format', 'access', 'metadata'):
                if current_pass(matches[0], gate):
                    continue
                candidate = preparer(repo, snapshot, confirmed, inputs, ledger, state, owner, run_id, item['collection'], item['candidate_id'], gate,
                    observed_heads={'review': review_head, 'main': main_head}, source_attempts=attempts, source_progress=progress,
                    at=clock(), heartbeat=heartbeat)
                keeper.check()
                if not isinstance(candidate, dict) or candidate.get('writes') != 0 or candidate.get('status') not in ('prepared', 'held'):
                    raise ValueError('Source gate proposal is invalid')
                if candidate['status'] == 'prepared':
                    proposal, chosen_gate = candidate, gate
                    break
            if proposal is not None:
                break
        if proposal is None:
            keeper.check()
            return {'status': 'deferred', 'reason': 'no_selected_source_gate', 'candidate_processing': False,
                    'native_completion_verified': False, 'lease_release_confirmed': False, 'publication_verified': False}
    if not isinstance(proposal.get('files'), dict):
        raise ValueError('Source gate proposal files unavailable')
    refs = heads(repo)
    if refs.get(REVIEW) != review_head or refs.get(MAIN) != main_head:
        raise ValueError('Source gate heads changed')
    response = send('source_gate', {'expectedHead': review_head, 'expectedMain': main_head, 'owner': owner,
                                    'runId': run_id, 'files': proposal['files']}, token)
    if not isinstance(response, dict) or response.get('status') != 'committed_and_read_back':
        return {'status': 'blocked', 'reason': 'source_gate_not_confirmed', 'reconcile_before_retry': True,
                'candidate_processing': None, 'native_completion_verified': False, 'lease_release_confirmed': False, 'publication_verified': False}
    commit, receipt = response.get('commit_sha'), response.get('receipt_path')
    if (not SHA.fullmatch(commit or '') or not isinstance(receipt, str) or not RECEIPT.fullmatch(receipt)
            or response.get('gate') != chosen_gate or response.get('candidate_processing') is not True
            or response.get('native_completion_verified') is not False or response.get('publication_verified') is not False):
        raise ValueError('Source gate response unconfirmed; reconcile before retrying')
    refs = heads(repo)
    if refs.get(REVIEW) != commit or refs.get(MAIN) != main_head:
        raise ValueError('Source gate head changed; reconcile before retrying')
    return {'status': 'checkpoint_confirmed_run_incomplete', 'commit_sha': commit, 'receipt_path': receipt, 'gate': chosen_gate,
            'candidate_processing': True, 'native_completion_verified': False, 'lease_release_confirmed': False, 'publication_verified': False}

"""Route evidence-only weekly gates and ordinary source preparation through their guarded writers."""
import json
import re
from datetime import datetime, timezone
from functools import partial

from tools.content_review.coordinator import plan
from tools.content_review.coordinator_lifecycle import complete as finish_empty
from tools.content_review.coordinator_source_cycle import _state, source_pass
from tools.content_review.coordinator_source_gate import checkpoint_one
from tools.content_review.coordinator_source_gate_completion import complete as finish_gate
from tools.content_review.coordinator_source_reservation import reserve
from tools.content_review.lifecycle import current_pass, evidence_key
from tools.content_review.manifest_integrity import reviewed_digest
from tools.content_review.site_reconcile_client import read_snapshot
from tools.content_review.source_gate_rules import audit
from tools.content_review.verified_inputs import _path_blob
from tools.content_review.weekly_source_checks import editorial_guard


OWNER = 'weekly-source-processing'
GATES = ('format', 'access', 'metadata')
RECEIPT = re.compile(r'config/content_review_source_receipts/[0-9a-f]{64}\.json')


def supported_gates(repo, review, row, at, receipts):
    retained = row.get('source_processing') or {}
    path = retained.get('receipt', '')
    if (retained.get('retrieval_status') != 'retrieved' or retained.get('content_sha256') != row['content_sha256']
            or not isinstance(path, str) or not RECEIPT.fullmatch(path)):
        return []
    if path not in receipts:
        raw, _ = _path_blob(repo, review, path)
        receipts[path] = json.loads(raw)
    try:
        checks = audit(row, 'weekly', receipts[path], now=at)['checks']
    except ValueError:
        # An older receipt may predate independently verified result provenance.
        # Such a receipt cannot advance this candidate's gate.
        return []
    return [g for g in GATES if not current_pass(row, g) and checks.get(g, {}).get('status') == 'passed'
                 and checks[g]['evidence']['request_id'] == path[-69:-5]]


def has_gate_evidence(repo, review):
    raw, _ = _path_blob(repo, review, 'config/weekly_review_manifest.json')
    manifest = json.loads(raw)
    rows = manifest.get('records', []) + manifest.get('preflight_records', [])
    if len(rows) > 10000:
        raise ValueError('Weekly source gate inventory exceeds its bound')
    receipts = {}
    now = datetime.now(timezone.utc)
    return any(supported_gates(repo, review, row, now, receipts) for row in rows
               if row.get('decision', 'pending') in ('pending', 'unreviewed')
               and row.get('publication_status') != 'published_live_verified' and not row.get('publication_approved')
               and current_pass(row, 'duplicates') and not all(current_pass(row, g) for g in GATES))


def select_gates(repo, snapshot, confirmed, inputs, owner, run_id, *, at, heartbeat):
    if owner != OWNER:
        raise ValueError('Weekly source gate scope differs')
    manifest = inputs['manifests']['weekly']
    rows = {row['candidate_id']: row for row in manifest.get('records', []) + manifest.get('preflight_records', [])}
    state, ledger = inputs['worker_state'], inputs['lifecycle']
    guard = editorial_guard(snapshot, confirmed, inputs['public'], inputs['exclusion_keys'])
    receipts, available = {}, {}

    def order(candidates):
        for item in candidates:
            cid = item['candidate_id']
            row = rows[cid]
            if item['collection'] != 'weekly':
                raise ValueError('Weekly source gate selected a different collection')
            if guard(row) or reviewed_digest(row) != row.get('content_sha256'):
                continue
            entry = ledger['records'].get('weekly:'+cid, {})
            if (entry.get('state') != 'awaiting_initial_checks' or
                entry.get('evidence_key') != evidence_key(row, inputs['lifecycle_policy']) or
                any(a.get('outcome') != 'success' for a in entry.get('attempts', []))):
                continue
            restriction = row.get('access_decision') or {}
            tlp = (row.get('source_observation') or {}).get('tlp')
            if (restriction.get('verified') and restriction.get('status') == 'restricted' or
                tlp and str(tlp).upper() not in ('TLP:CLEAR','TLP:WHITE')):
                continue
            supported = supported_gates(repo, inputs['review_commit'], row, at, receipts)
            if supported:
                available[cid] = supported
        return {cid: 0 for cid in available}

    choices = plan(snapshot, confirmed, inputs['reconciliation_manifests'], ledger, inputs['registry'], state,
                   owner, run_id, source_attempts=state.get('source_attempts', {}), source_progress=state.get('source_last_progress', {}),
                   at=at, heartbeat=heartbeat, review_head=inputs['review_commit'], stages=('source','metadata'),
                   retained_source_only=True, weekly_source_order=order)
    for item in choices['selected']:
        item['supported_gates'] = available[item['candidate_id']]
    return choices


def weekly_pass(repo, token, native, review, main, owner, run_id, *, state_reader=_state,
                gate=checkpoint_one, complete_gate=finish_gate, source=source_pass, empty=finish_empty, gate_evidence=has_gate_evidence):
    if owner != OWNER:
        raise ValueError('Weekly source working scope differs')
    state = state_reader(repo, review)
    pending = state['current_run'].get('pending_source_request')
    read = partial(read_snapshot, include_drafts=True)
    normal = partial(source, reserver=partial(reserve, snapshot_reader=read))
    args = (repo, token, native, review, main, owner, run_id)
    if pending is not None or not gate_evidence(repo, review):
        return normal(*args)
    def check():
        result = gate(repo, token, review, main, owner, run_id, snapshot_reader=read)
        if result.get('status') == 'deferred' and result.get('reason') == 'no_selected_source_gate':
            return None
        if result.get('status') != 'checkpoint_confirmed_run_incomplete':
            return result
        return complete_gate(repo, token, native, result['commit_sha'], main, owner, run_id, result['receipt_path'], snapshot_reader=read)
    prior = (state.get('run_history') or [{}])[-1]
    last = (state.get('source_attempts') or {}).get('weekly') or {}
    if last.get('run_id') == prior.get('run_id') and last.get('gate') in GATES:
        # Give retrieval/retention the next opportunity. With no source work,
        # the lease is still live and may serve another evidenced gate.
        def fallback(*finish_args):
            return check() or empty(*finish_args)
        return normal(*args, empty_finish=fallback)
    return check() or normal(*args)

"""Read-only verification of a scheduled receipt and checkpoint gate changes.

The caller must fetch native scheduler metadata and Git tree/blob metadata
independently. This module never writes state, acquires a lease or dispatches.
"""
import json
import re

from tools.content_review.lifecycle import GATES, current_pass, instant
from tools.content_review.manifest_integrity import parse, validate_update
from tools.content_review.snapshot_integrity import verify_bytes

RUN_ID = re.compile(r'^[a-zA-Z0-9-]+$')
CONTENT_HASH = re.compile(r'^[0-9a-f]{64}$')


def _blob(item):
    if not isinstance(item, dict):
        raise ValueError('Missing independently fetched blob')
    content = item.get('content')
    if not isinstance(content, (bytes, str)):
        raise ValueError('Incomplete independently fetched blob')
    verify_bytes(content, item.get('sha'), item.get('size'))
    return content.decode('utf-8') if isinstance(content, bytes) else content


def observe(native, receipt_blob, manifests):
    """Verify native completion, canonical receipt, and exact checkpoint diffs.

    A caller is responsible for authenticating native/tree metadata, selecting
    the correct commits and ensuring complete coverage. A gate transition is
    evidence of a checkpoint change, not independent proof of publication or
    that the underlying source actually supports the recorded evidence.
    """
    if not isinstance(native, dict) or not isinstance(native.get('id'), str) or not RUN_ID.fullmatch(native['id']):
        raise ValueError('Missing native run identity')
    if native.get('recorded_status') != 'completed' or native.get('trigger') != 'schedule':
        raise ValueError('Native scheduled completion is not confirmed')
    receipt = json.loads(_blob(receipt_blob))
    path = 'config/content_review_run_receipts/' + native['id'] + '.json'
    if (receipt_blob.get('path') != path or receipt.get('receipt_path') != path
        or receipt.get('run_id') != native['id'] or receipt.get('trigger') != 'schedule'
        or receipt.get('status') != 'complete' or not isinstance(receipt.get('completed_actions'), list)
        or not receipt['completed_actions']):
        raise ValueError('Canonical scheduled receipt is missing or mismatched')
    scheduled, started, completed, done = (instant(native.get('scheduled_for')),
        instant(native.get('started_at')), instant(native.get('completed_at')), instant(receipt.get('completed_at')))
    if not all((scheduled, started, completed, done)) or instant(receipt.get('scheduled_for')) != scheduled or not started <= done <= completed:
        raise ValueError('Native run and receipt timestamps do not agree')
    pilot = receipt.get('pilot') or {}
    if (pilot.get('integrity_passed') is not True or pilot.get('budget_compliant') is not True
        or pilot.get('access_rules_preserved') is not True or pilot.get('heartbeat_interval_compliant') is not True
        or pilot.get('lease_conflicts') != 0
        or pilot.get('checkpoint_failures') != 0):
        raise ValueError('Checkpoint, budget, access or lease evidence is incomplete')
    claims = pilot.get('newly_passed_checks')
    if not isinstance(claims, dict) or any(k not in GATES or not isinstance(v, list) for k, v in claims.items()):
        raise ValueError('Missing or malformed gate claims')
    if not isinstance(manifests, dict):
        raise ValueError('Missing manifest evidence')
    attempted = pilot.get('attempted_candidate_ids')
    if not isinstance(attempted, list):
        raise ValueError('Missing actual candidate attempts')
    # Ambiguous IDs cannot establish which collection changed.
    occurrences, changed = {}, []
    pairs = []
    for collection, pair in manifests.items():
        if not isinstance(pair, dict) or pair.get('path') not in receipt.get('checkpoint_paths', []):
            raise ValueError('Manifest is not named in the canonical checkpoint')
        before, after = _blob(pair.get('before')), _blob(pair.get('after'))
        try:
            validate_update(before, after)
            _, old = parse(before); _, new = parse(after)
            if any(old[cid].get('decision') != new[cid].get('decision') for cid in old.keys() & new.keys()):
                raise ValueError('Decision change requires separate D1 reconciliation evidence')
        except (ValueError, TypeError, KeyError) as exc:
            raise ValueError('Manifest integrity or decision preservation failed') from exc
        pairs.append((collection, old, new))
        for cid in set(old) | set(new):
            occurrences[cid] = occurrences.get(cid, 0) + 1
    for collection, old, new in pairs:
        for cid in old.keys() & new.keys():
            a, b = old[cid], new[cid]
            if (occurrences[cid] != 1 or cid not in attempted
                or not isinstance(a.get('content_sha256'), str) or not CONTENT_HASH.fullmatch(a['content_sha256'])
                or a.get('content_sha256') != b.get('content_sha256')):
                continue
            for gate in GATES:
                if cid not in claims.get(gate, []) or current_pass(a, gate) or not current_pass(b, gate):
                    continue
                checked = instant(b['preflight']['checks'][gate].get('checked_at'))
                if checked and started <= checked <= completed:
                    changed.append({'collection': collection, 'candidate_id': cid, 'gate': gate})
    return {'native_completion_verified': True, 'receipt_verified': True,
            'verified_checkpoint_gate_changes': changed,
            'unattended_recovery_verified': False,
            'note': 'Verified checkpoint transitions require separate source and publication verification.'}

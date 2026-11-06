"""A bounded local cycle using synthetic decisions and local source evidence."""
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import hashlib
import json

from tools.content_review.checkpoint import prepare
from tools.content_review.d1_reconcile import select_reconciled
from tools.content_review.duplicate_evidence import audit
from tools.content_review.independent_monitor import observe
from tools.content_review.lease import acquire


def git_blob(value, path=None):
    raw = json.dumps(value, sort_keys=True).encode()
    result = {'content': raw.decode(), 'size': len(raw),
              'sha': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}
    if path is not None:
        result['path'] = path
    return result


def test_synthetic_cycle_respects_decisions_lease_checkpoint_and_independent_monitor(tmp_path):
    at = datetime(2026, 11, 6, 20, 0, tzinfo=timezone.utc)
    h1, h2 = 'a' * 64, 'b' * 64
    decided = {'candidate_id': 'decided', 'review_number': 1, 'content_sha256': h1,
               'document_type': 'research_paper', 'decision': 'pending'}
    fresh = {'candidate_id': 'fresh', 'review_number': 2, 'content_sha256': h2,
             'document_type': 'research_paper', 'decision': 'pending', 'title': 'Different work',
             'authors': 'Author', 'year': 2026, 'abstract': '', 'preflight': {'checks': {}}}
    manifest = {'records': [decided, fresh], 'preflight_records': []}
    sub = {'id': 'submission', 'user_id': 'owner', 'collection': 'weekly', 'batch': 1,
           'revision': 1, 'accepted': 0, 'rejected': 1, 'payload_hash': 'c' * 64}
    decision = {'id': 'decision', 'submission_id': 'submission', 'user_id': 'owner',
                'collection': 'weekly', 'batch': 1, 'revision': 1, 'candidate_id': 'decided',
                'review_number': 1, 'content_sha256': h1, 'decision': 'rejected'}
    snapshot = {'submissions': [sub], 'decisions': [decision], 'jobs': []}
    snapshot['read_evidence'] = {key: {'complete': True, 'rows_received': len(snapshot[key]),
                                       'truncated_values': 0, 'omitted_columns': 0}
                                 for key in ('submissions', 'decisions', 'jobs')}
    ledger = {'records': {'weekly:' + cid: {'state': 'awaiting_initial_checks',
                        'first_seen_at': '2026-01-01'} for cid in ('decided', 'fresh')}}
    lease = acquire({'lease': None}, 'coordinator', 'run-1', at=at)['lease']
    plan = select_reconciled(snapshot, deepcopy(snapshot), {'weekly': manifest}, ledger)
    assert [item['candidate_id'] for item in plan['selected']] == ['fresh']
    assert manifest['records'][0]['decision'] == 'pending'  # No D1 decision was rewritten.

    result = audit(fresh, {'public': [{'candidate_id': 'other', 'title': 'Unrelated',
                                      'authors': 'Other', 'year': 2025}]}, [], set())
    assert result['status'] == 'passed'
    after = deepcopy(manifest)
    after['records'][1]['preflight']['checks']['duplicates'] = {
        'status': 'passed', 'content_sha256': h2, 'checked_at': (at + timedelta(minutes=1)).isoformat(),
        'evidence': {'matches': result['matches'], 'exclusions': result['exclusions'], 'source': 'fixture'}}
    path = 'config/weekly_review_manifest.json'
    (tmp_path / 'config').mkdir()
    (tmp_path / path).write_text(json.dumps(after, sort_keys=True))
    before_blob = git_blob(manifest)
    tree = prepare(tmp_path, [path], {path: before_blob}, lease, 'coordinator', at + timedelta(minutes=2))
    assert len(tree) == 1

    native = {'id': 'run-1', 'trigger': 'schedule', 'recorded_status': 'completed',
              'scheduled_for': at.isoformat(), 'started_at': at.isoformat(),
              'completed_at': (at + timedelta(minutes=4)).isoformat()}
    receipt_path = 'config/content_review_run_receipts/run-1.json'
    receipt = {'run_id': 'run-1', 'trigger': 'schedule', 'status': 'complete', 'receipt_path': receipt_path,
               'scheduled_for': at.isoformat(), 'completed_at': (at + timedelta(minutes=3)).isoformat(),
               'completed_actions': ['checkpoint'], 'checkpoint_paths': [path],
               'pilot': {'integrity_passed': True, 'budget_compliant': True, 'access_rules_preserved': True,
                         'heartbeat_interval_compliant': True, 'lease_conflicts': 0, 'checkpoint_failures': 0,
                         'attempted_candidate_ids': ['fresh'], 'newly_passed_checks': {'duplicates': ['fresh']}}}
    checked = observe(native, git_blob(receipt, receipt_path),
                      {'weekly': {'path': path, 'before': before_blob, 'after': git_blob(after)}})
    assert checked['verified_checkpoint_gate_changes'] == [
        {'collection': 'weekly', 'candidate_id': 'fresh', 'gate': 'duplicates'}]
    assert checked['unattended_recovery_verified'] is False

import hashlib
import json
from copy import deepcopy

import pytest

from tools.content_review.independent_monitor import observe


def blob(value, path=None):
    content = json.dumps(value, sort_keys=True)
    raw = content.encode()
    result = {'content': content, 'size': len(raw),
              'sha': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}
    if path is not None:
        result['path'] = path
    return result


def fixture():
    native = {'id': 'run-1', 'trigger': 'schedule', 'recorded_status': 'completed',
              'scheduled_for': '2026-11-06T20:00:00Z', 'started_at': '2026-11-06T20:00:01Z',
              'completed_at': '2026-11-06T20:05:00Z'}
    path = 'config/content_review_run_receipts/run-1.json'
    manifest_path = 'config/weekly_review_manifest.json'
    receipt = {'run_id': 'run-1', 'trigger': 'schedule', 'status': 'complete',
               'receipt_path': path, 'scheduled_for': native['scheduled_for'],
               'completed_at': '2026-11-06T20:04:00Z', 'completed_actions': ['checkpoint'],
               'checkpoint_paths': [manifest_path],
               'pilot': {'integrity_passed': True, 'budget_compliant': True,
                         'access_rules_preserved': True, 'heartbeat_interval_compliant': True,
                         'lease_conflicts': 0, 'checkpoint_failures': 0,
                         'attempted_candidate_ids': ['candidate'],
                         'newly_passed_checks': {'format': ['candidate']}}}
    before = {'records': [{'candidate_id': 'candidate', 'content_sha256': 'a' * 64,
                           'decision': 'pending', 'preflight': {'checks': {}}}]}
    after = deepcopy(before)
    after['records'][0]['preflight']['checks']['format'] = {
        'status': 'passed', 'content_sha256': 'a' * 64,
        'checked_at': '2026-11-06T20:03:00Z', 'evidence': 'Verified source'}
    manifests = {'weekly': {'path': manifest_path, 'before': blob(before), 'after': blob(after)}}
    return native, receipt, manifests


def test_observer_requires_native_schedule_and_verified_checkpoint_change():
    native, receipt, manifests = fixture()
    result = observe(native, blob(receipt, receipt['receipt_path']), manifests)
    assert result['receipt_verified'] is True
    assert result['verified_checkpoint_gate_changes'] == [
        {'collection': 'weekly', 'candidate_id': 'candidate', 'gate': 'format'}]
    assert result['unattended_recovery_verified'] is False


@pytest.mark.parametrize('change', [{'recorded_status': 'no_update'}, {'trigger': 'manual'},
                                  {'recorded_status': 'failed'}, {'requires_user_action': True},
                                  {'is_failure_message': True}])
def test_no_update_manual_and_failed_native_runs_are_not_verified(change):
    native, receipt, manifests = fixture()
    with pytest.raises(ValueError, match='Native scheduled completion'):
        observe({**native, **change}, blob(receipt, receipt['receipt_path']), manifests)


def test_empty_or_claimed_progress_does_not_become_a_verified_gate_change():
    native, receipt, manifests = fixture()
    manifests['weekly']['after'] = manifests['weekly']['before']
    result = observe(native, blob(receipt, receipt['receipt_path']), manifests)
    assert result['verified_checkpoint_gate_changes'] == []
    assert result['unattended_recovery_verified'] is False


def test_altered_blob_and_decision_change_fail_closed():
    native, receipt, manifests = fixture()
    bad_blob = blob(receipt, receipt['receipt_path'])
    bad_blob['content'] += ' '
    with pytest.raises(ValueError, match='Incomplete or altered'):
        observe(native, bad_blob, manifests)
    after = json.loads(manifests['weekly']['after']['content'])
    after['records'][0]['decision'] = 'approved'
    manifests['weekly']['after'] = blob(after)
    with pytest.raises(ValueError, match='decision preservation'):
        observe(native, blob(receipt, receipt['receipt_path']), manifests)

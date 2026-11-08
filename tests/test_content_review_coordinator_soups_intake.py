import json

from tools.content_review.coordinator_soups_intake import intake
from tools.content_review.coordinator_heartbeat_transport import REVIEW, MAIN, HEARTBEAT
from tests.test_content_review_coordinator_duplicate import Keeper


def context(monkeypatch):
    review, main, heartbeat, commit = 'a'*40, 'b'*40, 'c'*40, 'd'*40
    refs = {REVIEW: review, MAIN: main, HEARTBEAT: heartbeat}
    calls = []
    monkeypatch.setattr('tools.content_review.coordinator_soups_intake._path_blob',
                        lambda *a: (json.dumps({'beat': True}).encode(), {}))
    def pulse_factory(repo, token, head, *args):
        def pulse():
            calls.append(('pulse', head))
            return {'status': 'committed_and_read_back', 'commit_sha': 'e'*40}
        return pulse
    kw = dict(heads=lambda _: dict(refs), fetch=lambda *a: None,
              snapshot_reader=lambda _: ({}, {}),
              inputs_reader=lambda *a: {'worker_state': {}, 'lifecycle': {}},
              pulse_factory=pulse_factory, keeper_factory=Keeper,
              planner=lambda *a, **k: {'status': 'prepared'},
              guard=lambda *a, **k: {'bundle': {'status': 'prepared', 'writes': 0, 'files': {'x': 'y'}}})
    return review, main, commit, refs, calls, kw


def test_intake_requires_confirmed_write_and_rebinds_heartbeat(monkeypatch):
    review, main, commit, refs, calls, kw = context(monkeypatch)
    def send(action, payload, token):
        assert action == 'soups_intake' and not Keeper.active
        refs[REVIEW] = commit
        return {'status': 'committed_and_read_back', 'commit_sha': commit,
                'receipt_path': 'config/content_review_intake_receipts/'+'f'*64+'.json',
                'candidate_count': 5, 'candidate_processing': False, 'publication_verified': False}
    result = intake('.', 'token', review, main, 'owner', 'run', send=send, **kw)
    assert result['status'] == 'intake_confirmed'
    assert result['candidate_count'] == 5 and result['candidate_processing'] is False
    assert ('pulse', commit) in calls


def test_ambiguous_intake_does_not_retry(monkeypatch):
    review, main, commit, refs, calls, kw = context(monkeypatch)
    def send(*args):
        calls.append('write')
        return {'status': 'outcome_unknown'}
    result = intake('.', 'token', review, main, 'owner', 'run', send=send, **kw)
    assert result['reconcile_before_retry'] is True and calls.count('write') == 1
    assert result['candidate_processing'] is False


def test_no_intake_does_not_write(monkeypatch):
    review, main, commit, refs, calls, kw = context(monkeypatch)
    kw['planner'] = lambda *a, **k: {'status': 'no_soups_intake_due'}
    result = intake('.', 'token', review, main, 'owner', 'run',
                    send=lambda *a: (_ for _ in ()).throw(AssertionError('unexpected write')), **kw)
    assert result['status'] == 'deferred' and result['candidate_processing'] is False


def test_source_head_change_during_snapshot_prevents_write(monkeypatch):
    review, main, commit, refs, calls, kw = context(monkeypatch)
    def changed(_):
        refs[REVIEW] = commit
        return {}, {}
    kw['snapshot_reader'] = changed
    try:
        intake('.', 'token', review, main, 'owner', 'run', send=lambda *a: calls.append('write'), **kw)
        assert False, 'expected changed-head error'
    except ValueError as exc:
        assert 'heads changed' in str(exc)
    assert 'write' not in calls

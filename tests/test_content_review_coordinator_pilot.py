from tools.content_review.coordinator_pilot import run
from tools.content_review.coordinator_heartbeat_transport import REVIEW, MAIN

HEADS = lambda repo: {REVIEW: 'old', MAIN: 'main'}


def test_processed_pass_releases_only_after_verified_checkpoint():
    calls = []
    def begin(*args):
        return {'status': 'lease_started', 'review_head': 'old', 'main_head': 'main'}
    def checkpoint(*args):
        calls.append('checkpoint')
        return {'status': 'checkpoint_confirmed_run_incomplete', 'commit_sha': 'new', 'receipt_path': 'receipt'}
    def finish(*args):
        calls.append(args[3:])
        return {'status': 'application_complete', 'candidate_processing': True}
    result = run('.', 'token', {}, 'owner', 'run', heads=HEADS, begin=begin, pending_checker=lambda *a: False,
                 checkpoint=checkpoint, finish=finish)
    assert calls == ['checkpoint', ('new', 'main', 'owner', 'run', 'receipt')]
    assert result['candidate_processing'] is True


def test_pending_source_is_preserved_without_request_or_checkpoint():
    result = run('.', 'token', {}, 'owner', 'run',
                 heads=HEADS, begin=lambda *a: (_ for _ in ()).throw(AssertionError('unexpected lease')),
                 pending_checker=lambda *a: True,
                 checkpoint=lambda *a: (_ for _ in ()).throw(AssertionError('unexpected checkpoint')),
                 finish=lambda *a: (_ for _ in ()).throw(AssertionError('unexpected release')))
    assert result['reason'] == 'pending_source_requires_full_coordinator'
    assert result['candidate_processing'] is False


def test_ambiguous_checkpoint_is_never_released_as_success():
    failure = {'status': 'blocked', 'reconcile_before_retry': True}
    result = run('.', 'token', {}, 'owner', 'run',
                 heads=HEADS, begin=lambda *a: {'status': 'lease_started', 'review_head': 'old', 'main_head': 'main'},
                 pending_checker=lambda *a: False, checkpoint=lambda *a: failure,
                 finish=lambda *a: (_ for _ in ()).throw(AssertionError('unexpected release')))
    assert result == failure


def test_pending_source_race_after_lease_fails_closed():
    pending = iter([False, True])
    result = run('.', 'token', {}, 'owner', 'run', heads=HEADS,
                 begin=lambda *a: {'status': 'lease_started', 'review_head': 'old', 'main_head': 'main'},
                 pending_checker=lambda *a: next(pending),
                 checkpoint=lambda *a: (_ for _ in ()).throw(AssertionError('unexpected checkpoint')),
                 finish=lambda *a: (_ for _ in ()).throw(AssertionError('unexpected release')))
    assert result['reason'] == 'pending_source_changed_after_lease'
    assert result['reconcile_before_retry'] is True

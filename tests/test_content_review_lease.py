import json
import subprocess
from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from tools.content_review.lease import acquire, release, renew


NOW = datetime(2026, 11, 6, 20, 0, tzinfo=timezone.utc)


def test_lease_transitions_preserve_history_and_refuse_other_writers():
    initial = {'lease': None, 'lease_history': [{'run_id': 'historic'}], 'ready_total': 12}
    original = deepcopy(initial)
    held = acquire(initial, 'worker-a', 'run-a', at=NOW)
    assert initial == original and held['ready_total'] == 12
    with pytest.raises(ValueError, match='active lease'):
        acquire(held, 'worker-b', 'run-b', at=NOW + timedelta(seconds=1))
    with pytest.raises(ValueError, match='matching unexpired'):
        renew(held, 'worker-b', 'run-b', at=NOW + timedelta(seconds=1))
    renewed = renew(held, 'worker-a', 'run-a', at=NOW + timedelta(minutes=1))
    closed = release(renewed, 'worker-a', 'run-a', at=NOW + timedelta(minutes=2))
    assert closed['lease'] is None and closed['lease_history'][0] == {'run_id': 'historic'}
    assert closed['lease_history'][-1]['run_id'] == 'run-a'
    assert closed['lease_history'][-1]['status'] == 'released'
    with pytest.raises(ValueError, match='cannot be reused'):
        acquire(closed, 'worker-a', 'run-a', at=NOW + timedelta(minutes=3))


def test_expired_lease_is_recorded_and_stale_owner_cannot_renew_or_release():
    first = acquire({'lease': None}, 'a', 'run-a', seconds=60, at=NOW)
    later = NOW + timedelta(seconds=60)
    for action in (renew, release):
        with pytest.raises(ValueError, match='unexpired'):
            action(first, 'a', 'run-a', at=later)
    with pytest.raises(ValueError, match='cannot be reused'):
        acquire(first, 'a', 'run-a', at=later)
    second = acquire(first, 'b', 'run-b', at=later)
    assert second['lease']['run_id'] == 'run-b'
    assert second['lease_history'][-1]['run_id'] == 'run-a'
    assert second['lease_history'][-1]['status'] == 'expired'
    with pytest.raises(ValueError, match='unexpired'):
        release(second, 'a', 'run-a', at=later)


def test_lease_cannot_be_renewed_or_released_before_it_was_acquired():
    state = acquire({'lease': None}, 'a', 'run-a', at=NOW)
    for action in (renew, release):
        with pytest.raises(ValueError, match='cannot precede'):
            action(state, 'a', 'run-a', at=NOW - timedelta(seconds=1))


def test_two_claims_from_same_git_head_cannot_both_publish(tmp_path):
    def git(*args, data=None, check=True):
        return subprocess.run(['git', '-C', str(tmp_path), '-c', 'user.name=Test',
                               '-c', 'user.email=test@example.test', *args], input=data,
                              text=True, capture_output=True, check=check)
    git('init', '--quiet')
    empty_tree = git('mktree', data='').stdout.strip()
    base = git('commit-tree', empty_tree, '-m', 'base').stdout.strip()
    git('update-ref', 'refs/heads/review', base)
    def commit_for(owner):
        state = acquire({'lease': None}, owner, 'run-' + owner, at=NOW)
        blob = git('hash-object', '-w', '--stdin', data=json.dumps(state)).stdout.strip()
        tree = git('mktree', data=f'100644 blob {blob}\tstate.json\n').stdout.strip()
        return git('commit-tree', tree, '-p', base, '-m', owner).stdout.strip()
    first, competing = commit_for('a'), commit_for('b')
    assert git('update-ref', 'refs/heads/review', first, base, check=False).returncode == 0
    assert git('update-ref', 'refs/heads/review', competing, base, check=False).returncode != 0
    assert git('rev-parse', 'refs/heads/review').stdout.strip() == first

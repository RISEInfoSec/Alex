from copy import deepcopy

import pytest

from tools.content_review.d1_reconcile import SnapshotError, reconcile


def fixture():
    h = 'a' * 64
    sub = dict(id='s1', user_id='owner', collection='weekly', batch=1, revision=1,
               accepted=1, rejected=1, payload_hash='b' * 64)
    def decision(cid, choice):
        return dict(id='d-' + cid, user_id='owner', submission_id='s1', collection='weekly',
                    batch=1, revision=1, candidate_id=cid, review_number=1 if cid == 'a' else 2,
                    content_sha256=h, decision=choice, recommendation_snapshot='original evidence')
    snapshot = {'submissions': [sub], 'decisions': [decision('a', 'approved'), decision('b', 'rejected')],
                'jobs': [dict(id='j1', user_id='owner', submission_id='s1', collection='weekly',
                              revision=1, kind='mechanical_assessment', candidate_id='a', content_sha256=h)]}
    manifests = {'weekly': [dict(candidate_id='a', content_sha256=h, review_number=1),
                            dict(candidate_id='b', content_sha256=h, review_number=2)]}
    return snapshot, manifests


def test_matching_snapshot_retains_exact_decisions_and_does_not_mutate_inputs():
    snapshot, manifests = fixture()
    original = deepcopy(snapshot)
    result = reconcile(snapshot, deepcopy(snapshot), manifests)
    assert result['counts']['matched'] == 2 and result['counts']['held'] == 0
    assert result['matched_decisions'] == original['decisions']
    assert snapshot == original
    assert result['transactional_snapshot'] is False and result['requires_recheck_under_lease'] is True


def test_changed_second_read_or_incomplete_submission_fails_closed():
    snapshot, manifests = fixture()
    changed = deepcopy(snapshot)
    changed['decisions'][0]['decision'] = 'rejected'
    with pytest.raises(SnapshotError, match='changed between reads'):
        reconcile(snapshot, changed, manifests)
    incomplete = deepcopy(snapshot)
    incomplete['decisions'].pop()
    with pytest.raises(SnapshotError, match='Incomplete submission'):
        reconcile(incomplete, deepcopy(incomplete), manifests)


def test_content_change_is_held_not_rebound():
    snapshot, manifests = fixture()
    manifests['weekly'][0]['content_sha256'] = 'c' * 64
    manifests['weekly'].pop()
    result = reconcile(snapshot, deepcopy(snapshot), manifests)
    assert result['counts']['matched'] == 0
    assert {x['reason'] for x in result['held']} == {'reviewed_content_changed', 'missing_manifest_candidate'}


def test_latest_revision_only_but_prior_evidence_is_preserved():
    snapshot, manifests = fixture()
    later = deepcopy(snapshot['submissions'][0])
    later.update(id='s2', revision=2, accepted=0, rejected=1)
    new = deepcopy(snapshot['decisions'][0])
    new.update(id='d-later', submission_id='s2', revision=2, decision='rejected')
    snapshot['submissions'].append(later)
    snapshot['decisions'].append(new)
    before = deepcopy(snapshot)
    result = reconcile(snapshot, deepcopy(snapshot), manifests)
    assert result['counts']['decisions'] == 3 and result['counts']['active_decisions'] == 1
    assert result['matched_decisions'][0]['id'] == 'd-later'
    assert snapshot == before


def test_conflicting_active_decisions_are_held():
    snapshot, manifests = fixture()
    other_sub = deepcopy(snapshot['submissions'][0])
    other_sub.update(id='s2', user_id='second-owner', accepted=1, rejected=0)
    other_decision = deepcopy(snapshot['decisions'][0])
    other_decision.update(id='d2', user_id='second-owner', submission_id='s2')
    snapshot['submissions'].append(other_sub)
    snapshot['decisions'].append(other_decision)
    result = reconcile(snapshot, deepcopy(snapshot), manifests)
    assert result['counts']['matched'] == 1
    assert result['held'][0]['reason'] == 'conflicting_active_decisions'


def test_jobs_must_match_the_original_hash_and_decision():
    snapshot, manifests = fixture()
    snapshot['jobs'][0]['content_sha256'] = 'c' * 64
    with pytest.raises(SnapshotError, match='Job reviewed content mismatch'):
        reconcile(snapshot, deepcopy(snapshot), manifests)

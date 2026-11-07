from copy import deepcopy

import pytest

from tools.content_review.d1_reconcile import SnapshotError, reconcile, select_reconciled


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
    snapshot['read_evidence'] = {key: {'complete': True, 'rows_received': len(snapshot[key]),
                                        'truncated_values': 0, 'omitted_columns': 0}
                                 for key in ('submissions', 'decisions', 'jobs')}
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
    incomplete['read_evidence']['decisions']['rows_received'] -= 1
    with pytest.raises(SnapshotError, match='Incomplete submission'):
        reconcile(incomplete, deepcopy(incomplete), manifests)


def test_content_change_is_held_not_rebound():
    snapshot, manifests = fixture()
    manifests['weekly'][0]['content_sha256'] = 'c' * 64
    manifests['weekly'].pop()
    result = reconcile(snapshot, deepcopy(snapshot), manifests)
    assert result['counts']['matched'] == 0
    assert {x['reason'] for x in result['held']} == {'reviewed_content_changed', 'missing_manifest_candidate'}


def test_changed_batch_is_held_even_when_candidate_hash_matches():
    snapshot, manifests = fixture()
    manifests['weekly'][0]['review_batch'] = 2
    result = reconcile(snapshot, deepcopy(snapshot), manifests)
    assert result['counts']['matched'] == 1
    assert result['held'][0]['reason'] == 'review_batch_changed_or_unknown'


def test_soups_legacy_batch_and_apwg_unknown_batch_are_not_guessed():
    from tools.content_review.d1_reconcile import _review_batch
    assert _review_batch('soups', {'review_number': 118}) == 6
    assert _review_batch('soups', {'review_number': 119}) == 7
    assert _review_batch('soups', {'review_number': 121, 'review_batch': 9}) == 9
    assert _review_batch('apwg', {'review_number': 4}) is None


def test_latest_revision_only_but_prior_evidence_is_preserved():
    snapshot, manifests = fixture()
    later = deepcopy(snapshot['submissions'][0])
    later.update(id='s2', revision=2, accepted=0, rejected=1)
    new = deepcopy(snapshot['decisions'][0])
    new.update(id='d-later', submission_id='s2', revision=2, decision='rejected')
    snapshot['submissions'].append(later)
    snapshot['decisions'].append(new)
    snapshot['read_evidence']['submissions']['rows_received'] += 1
    snapshot['read_evidence']['decisions']['rows_received'] += 1
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
    snapshot['read_evidence']['submissions']['rows_received'] += 1
    snapshot['read_evidence']['decisions']['rows_received'] += 1
    result = reconcile(snapshot, deepcopy(snapshot), manifests)
    assert result['counts']['matched'] == 1
    assert result['held'][0]['reason'] == 'conflicting_active_decisions'


def test_jobs_must_match_the_original_hash_and_decision():
    snapshot, manifests = fixture()
    snapshot['jobs'][0]['content_sha256'] = 'c' * 64
    with pytest.raises(SnapshotError, match='Job reviewed content mismatch'):
        reconcile(snapshot, deepcopy(snapshot), manifests)


def test_missing_or_incomplete_reader_evidence_never_masquerades_as_an_empty_database():
    snapshot, manifests = fixture()
    del snapshot['read_evidence']['decisions']
    with pytest.raises(SnapshotError, match='Missing decisions read evidence'):
        reconcile(snapshot, deepcopy(snapshot), manifests)


def test_selection_excludes_decided_and_changed_content_without_mutating_manifests():
    snapshot, rows = fixture()
    rows['weekly'][1]['content_sha256'] = 'c' * 64
    rows['weekly'].append(dict(candidate_id='c', content_sha256='d' * 64, review_number=3,
                               document_type='research_paper', decision='pending', abstract=''))
    manifests = {'weekly': {'records': rows['weekly'], 'preflight_records': []}}
    original = deepcopy(manifests)
    ledger = {'records': {'weekly:' + c: {'state': 'awaiting_initial_checks', 'first_seen_at': '2026-01-01'}
                          for c in ('a', 'b', 'c')}}
    result = select_reconciled(snapshot, deepcopy(snapshot), manifests, ledger)
    assert [row['candidate_id'] for row in result['selected']] == ['c']
    assert result['reconciliation']['counts']['matched'] == 1
    assert result['reconciliation']['counts']['held'] == 1
    assert manifests == original


def test_selection_holds_candidates_with_missing_or_malformed_content_hashes():
    snapshot, rows = fixture()
    rows['weekly'].extend([dict(candidate_id='c', content_sha256=None, review_number=3),
                           dict(candidate_id='d', content_sha256=42, review_number=4)])
    manifests = {'weekly': {'records': rows['weekly']}}
    ledger = {'records': {'weekly:' + cid: {'state': 'awaiting_initial_checks', 'first_seen_at': '2026-01-01'}
                          for cid in ('a', 'b', 'c', 'd')}}
    assert select_reconciled(snapshot, deepcopy(snapshot), manifests, ledger)['selected'] == []

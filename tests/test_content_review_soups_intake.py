from copy import deepcopy
from datetime import timedelta

import pytest

from tests.test_content_review_duplicate_stage import fixture
from tools.content_review.soups_intake import prepare, URL


def setup():
    now, snapshot, inputs, state, _ = fixture()
    row = deepcopy(inputs['manifests']['weekly']['records'][0])
    row.pop('review_number')
    manifest = {'records': [row], 'preflight_records': [], 'sealed_review_batches': []}
    inputs['registry'] = [{'id': 'soups', 'adapter': 'soups', 'manifest_url': URL}]
    inputs['manifests'] = {'soups': manifest}
    inputs['reconciliation_manifests'] = deepcopy(inputs['manifests'])
    inputs['lifecycle'] = {'records': {}}
    inputs['lifecycle_policy'] = {'version': 1}
    inputs['metadata'].append({'commit': inputs['review_commit'], 'path': 'config/soups_review_manifest.json'})
    return now, snapshot, inputs, state, inputs['lifecycle']


def call(now, snapshot, inputs, state, ledger, confirmed=None):
    return prepare(snapshot, deepcopy(snapshot) if confirmed is None else confirmed, inputs, ledger, state,
                   'worker', 'run', observed_heads={'review': 'a' * 40, 'main': 'b' * 40},
                   source_attempts={}, source_progress={}, at=now)


def test_unnumbered_intake_reserves_only_and_preserves_source_and_hash():
    now, snap, inputs, state, ledger = setup()
    original = deepcopy((snap, inputs, state, ledger))
    result = call(now, snap, inputs, state, ledger)
    row = result['proposed_manifest']['records'][0]
    assert result['status'] == 'prepared' and result['selected'] == ['fresh']
    assert row['reserved_review_number'] == row['reserved_review_batch'] == 1
    assert 'review_number' not in row and not row.get('review_ready')
    assert row['content_sha256'] == inputs['manifests']['soups']['records'][0]['content_sha256']
    assert row['decision'] == 'pending' and result['proposed_ledger']['records']['soups:fresh']['attempts'] == []
    assert result['writes'] == 0 and result['candidate_processing'] is False
    assert result['requires_semantic_guard_and_live_recheck'] is True
    assert (snap, inputs, state, ledger) == original


def test_intake_is_bounded_and_respects_existing_number_and_batch_reservations():
    now, snap, inputs, state, ledger = setup()
    m = inputs['manifests']['soups']
    base = m['records'][0]
    for n in range(8):
        r = deepcopy(base);r['candidate_id'] = 'new-' + str(n);m['records'].append(r)
    prior = deepcopy(base);prior.update(candidate_id='old', review_number=20, review_batch=4)
    m['records'].append(prior);m['sealed_review_batches'].append({'batch': 9})
    inputs['reconciliation_manifests'] = deepcopy(inputs['manifests'])
    result = call(now, snap, inputs, state, ledger)
    chosen = [r for r in result['proposed_manifest']['records'] if r['candidate_id'] in result['selected']]
    assert len(chosen) == 5
    assert {r['reserved_review_number'] for r in chosen} == {21, 22, 23, 24, 25}
    assert {r['reserved_review_batch'] for r in chosen} == {10}
    assert all('review_number' not in r for r in chosen)


def test_conflicting_reservations_and_changed_snapshot_fail_closed():
    now, snap, inputs, state, ledger = setup()
    rows = inputs['manifests']['soups']['records']
    rows[0]['reserved_review_number'] = 1
    other = deepcopy(rows[0]);other['candidate_id'] = 'other';rows.append(other)
    inputs['reconciliation_manifests'] = deepcopy(inputs['manifests'])
    with pytest.raises(ValueError, match='Conflicting SOUPS review number'):
        call(now, snap, inputs, state, ledger)
    rows.pop();inputs['reconciliation_manifests'] = deepcopy(inputs['manifests'])
    changed = deepcopy(snap);changed['read_evidence']['jobs']['complete'] = False
    with pytest.raises(ValueError, match='Incomplete jobs'):
        call(now, snap, inputs, state, ledger, changed)
    state['lease']['expires_at'] = (now + timedelta(seconds=119)).isoformat()
    inputs['worker_state'] = deepcopy(state)
    with pytest.raises(ValueError, match='reserve'):
        call(now, snap, inputs, state, ledger)


def test_stale_hash_and_preexisting_review_readiness_are_held():
    now, snap, inputs, state, ledger = setup()
    row = inputs['manifests']['soups']['records'][0]
    row['title'] = 'Changed content'
    inputs['reconciliation_manifests'] = deepcopy(inputs['manifests'])
    result = call(now, snap, inputs, state, ledger)
    assert result['status'] == 'no_soups_intake_due' and result['held']['reviewed_content_hash_mismatch'] == 1
    row['review_ready'] = True
    inputs['reconciliation_manifests'] = deepcopy(inputs['manifests'])
    result = call(now, snap, inputs, state, ledger)
    assert result['held']['inconsistent_readiness'] == 1


def test_record_with_prior_d1_decision_is_never_reserved():
    now, snap, inputs, state, ledger = setup()
    row = inputs['manifests']['soups']['records'][0]
    snap['submissions'] = [dict(id='s', user_id='owner', collection='soups', batch=1,
        revision=1, accepted=0, rejected=1, payload_hash='a' * 64)]
    snap['decisions'] = [dict(id='d', user_id='owner', submission_id='s', collection='soups',
        batch=1, revision=1, candidate_id='fresh', review_number=1,
        content_sha256=row['content_sha256'], decision='rejected')]
    for name in ('submissions', 'decisions'):
        snap['read_evidence'][name]['rows_received'] = len(snap[name])
    result = call(now, snap, inputs, state, ledger)
    assert result['status'] == 'no_soups_intake_due' and result['writes'] == 0


def test_existing_reservation_is_retained_and_never_makes_candidate_ready():
    now, snap, inputs, state, ledger = setup()
    row = inputs['manifests']['soups']['records'][0]
    row.update(reserved_review_number=200, reserved_review_batch=11)
    inputs['reconciliation_manifests'] = deepcopy(inputs['manifests'])
    result = call(now, snap, inputs, state, ledger)
    row = result['proposed_manifest']['records'][0]
    assert row['reserved_review_number'] == 200 and row['reserved_review_batch'] == 11
    assert 'review_number' not in row and not row.get('review_ready')

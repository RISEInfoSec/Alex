from copy import deepcopy
from datetime import timedelta

import pytest

from tests.test_content_review_duplicate_stage import fixture
from tools.content_review.soups_intake import prepare, URL


def setup():
    now, snapshot, inputs, state, _ = fixture()
    row = deepcopy(inputs['manifests']['weekly']['records'][0])
    row.pop('review_number')
    row.pop('preflight')
    row['candidate_id'] = 'soups-fresh'
    row['screening_status'] = 'not_assessed'
    manifest = {'records': [row], 'preflight_records': [], 'sealed_review_batches': []}
    inputs['registry'] = [{'id': 'soups', 'adapter': 'soups', 'manifest_url': URL}]
    inputs['manifests'] = {'soups': manifest}
    inputs['reconciliation_manifests'] = deepcopy(inputs['manifests'])
    inputs['lifecycle'] = {'records': {}}
    inputs['lifecycle_policy'] = {'version': 1}
    inputs['preflight_status'] = {'records': [], 'summary': {}}
    inputs['metadata'].append({'commit': inputs['review_commit'], 'path': 'config/soups_review_manifest.json'})
    inputs['metadata'].append({'commit': inputs['review_commit'], 'path': 'config/content_review_preflight_status.json'})
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
    assert result['status'] == 'prepared' and result['selected'] == ['soups-fresh']
    assert row['reserved_review_number'] == row['reserved_review_batch'] == 1
    assert 'review_number' not in row and not row.get('review_ready')
    assert row['content_sha256'] == inputs['manifests']['soups']['records'][0]['content_sha256']
    assert row['decision'] == 'pending' and result['proposed_ledger']['records']['soups:soups-fresh']['attempts'] == []
    stage = result['proposed_stage']['records'][0]
    assert stage['review_ready'] is False and stage['status'] == 'held'
    assert stage['checks'] == row['preflight']['checks'] == {}
    assert result['writes'] == 0 and result['candidate_processing'] is False
    assert result['requires_semantic_guard_and_live_recheck'] is True
    assert (snap, inputs, state, ledger) == original


def test_intake_is_bounded_and_respects_existing_number_and_batch_reservations():
    now, snap, inputs, state, ledger = setup()
    m = inputs['manifests']['soups']
    base = m['records'][0]
    for n in range(8):
        r = deepcopy(base);r['candidate_id'] = 'soups-new-' + str(n);m['records'].append(r)
    prior = deepcopy(base);prior.update(candidate_id='soups-old', review_number=20, review_batch=4)
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
        batch=1, revision=1, candidate_id='soups-fresh', review_number=1,
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


def test_existing_stage_is_held_for_reconciliation_not_overwritten():
    now, snap, inputs, state, ledger = setup()
    stage = inputs['preflight_status']
    stage['records'].append({'collection': 'soups', 'candidate_id': 'soups-fresh', 'checks': {}})
    from tools.content_review.stage_summary import derive
    stage['summary'] = derive(stage['records'])
    before = deepcopy(stage)
    result = call(now, snap, inputs, state, ledger)
    assert result['status'] == 'no_soups_intake_due'
    assert result['held']['existing_preflight_stage_requires_reconciliation'] == 1
    assert stage == before


def test_intake_skips_assessed_or_restricted_rows_without_blocking_untouched_peers():
    now, snap, inputs, state, ledger = setup()
    rows = inputs['manifests']['soups']['records']
    assessed = deepcopy(rows[0]); assessed.update(candidate_id='soups-a', screening_status='abstract_reviewed')
    restricted = deepcopy(rows[0]); restricted.update(candidate_id='soups-b', access_decision={'verified': True, 'status': 'restricted'})
    existing = deepcopy(rows[0]); existing.update(candidate_id='soups-c', preflight={'checks': {}})
    rows[:0] = [assessed, restricted, existing]
    inputs['reconciliation_manifests'] = deepcopy(inputs['manifests'])
    result = call(now, snap, inputs, state, ledger)
    assert result['selected'] == ['soups-fresh']
    assert result['held']['outside_untouched_intake_scope'] == 3
    assert result['proposed_manifest']['records'][:3] == [assessed, restricted, existing]


def test_paper_only_intake_keeps_nonpaper_history_and_allows_missing_doi():
    from tools.content_review.manifest_integrity import reviewed_digest
    now, snap, inputs, state, ledger = setup()
    rows = inputs['manifests']['soups']['records']
    assert not rows[0]['doi']
    poster = deepcopy(rows[0]); poster.update(candidate_id='soups-a', document_type='poster_or_poster_showcase')
    poster['content_sha256'] = reviewed_digest(poster)
    talk = deepcopy(rows[0]); talk.update(candidate_id='soups-b', document_type='invited_talk_or_other_program_item')
    talk['content_sha256'] = reviewed_digest(talk)
    rows[:0] = [poster, talk]
    inputs['reconciliation_manifests'] = deepcopy(inputs['manifests'])
    result = call(now, snap, inputs, state, ledger)
    assert result['selected'] == ['soups-fresh']
    assert result['held']['outside_soups_paper_intake'] == 2
    assert result['proposed_manifest']['records'][:2] == [poster, talk]
    assert result['proposed_manifest']['records'][2]['reserved_review_number'] == 1
    assert result['proposed_manifest']['records'][2]['doi'] == ''
    assert result['proposed_stage']['records'][0]['review_ready'] is False

import copy

import pytest

from tests.test_content_review_bind_recommendations import fixture
from tools.content_review.bind_recommendations import bind_record
from tools.content_review.admit_cleared import admit


def inputs(count=21):
    rows, stages = [], []
    for i in range(count):
        row, stage = fixture()
        row['candidate_id'] = stage['candidate_id'] = f'weekly-{i}'
        row.update(review_number=i+1, review_batch=1, batch=1)
        bind_record(row, stage)
        rows.append(row)
        stages.append(stage)
    return {'records': [], 'preflight_records': rows, 'new_batches_must_be_full': False}, {'records': stages}


def test_seals_ready_candidates_without_waiting_for_held_reservations():
    manifest, stage = inputs()
    held = copy.deepcopy(manifest['preflight_records'][0])
    held['candidate_id'] = 'held'
    held['batch_admission_eligible'] = False
    held['preflight']['checks']['schema']['status'] = 'held'
    manifest['preflight_records'].append(held)
    result, checkpoint, receipt = admit(manifest, stage, 'weekly', submitted_batches=[8])
    assert [b['count'] for b in receipt['batches']] == [20, 1]
    assert [b['batch'] for b in receipt['batches']] == [9, 10]
    assert result['preflight_records'] == [held]
    assert result['ready_count'] == 21
    assert [r['content_sha256'] for r in result['records']] == [r['content_sha256'] for r in manifest['preflight_records'][:-1]]
    replay, _, again = admit(result, checkpoint, 'weekly', submitted_batches=[9])
    assert replay == result
    assert again['admitted'] == 0


@pytest.mark.parametrize('fault', ['hash', 'stale', 'recommendation'])
def test_admission_refuses_stale_evidence(fault):
    manifest, stage = inputs(1)
    row = manifest['preflight_records'][0]
    if fault == 'hash':
        row['preflight']['checks']['access']['content_sha256'] = 'bad'
    elif fault == 'stale':
        row['preflight']['checks']['access']['stale'] = True
    else:
        row['recommendation_content_sha256'] = 'bad'
    with pytest.raises(ValueError):
        admit(manifest, stage, 'weekly')


def test_live_decision_excludes_candidate_from_admission():
    manifest, stage = inputs(1)
    result, _, receipt = admit(manifest, stage, 'weekly', decided_ids=['weekly-0'])
    assert receipt['admitted'] == 0 and result['records'] == []


def test_full_batch_policy_keeps_cleared_remainder_without_reopening_sealed_batch():
    manifest, stage = inputs(21)
    manifest['new_batches_must_be_full'] = True
    result, checkpoint, receipt = admit(manifest, stage, 'weekly', submitted_batches=[23])
    assert [(b['batch'], b['count']) for b in receipt['batches']] == [(24, 20)]
    assert receipt['cleared_awaiting_full_batch'] == 1
    assert len(result['preflight_records']) == 1
    assert result['preflight_records'][0]['candidate_id'] == 'weekly-20'
    assert result['mechanical_passed_awaiting_batch_admission'] == 1
    replay, _, again = admit(result, checkpoint, 'weekly', submitted_batches=[24])
    assert replay == result
    assert again['admitted'] == 0
    assert again['cleared_awaiting_full_batch'] == 1


def test_new_manifests_default_to_full_batches():
    manifest, stage = inputs(1)
    del manifest['new_batches_must_be_full']
    result, _, receipt = admit(manifest, stage, 'weekly')
    assert receipt['admitted'] == 0
    assert result['mechanical_passed_awaiting_batch_admission'] == 1
    assert result['records'] == []

import json
from copy import deepcopy
from datetime import timedelta

import pytest

from tests.test_content_review_duplicate_stage import fixture
from tools.content_review.duplicate_checkpoint import prepare
from tools.content_review.lifecycle import evaluate
from tools.content_review.stage_summary import derive


def setup_bundle():
    now, snapshot, inputs, state, _ = fixture()
    row = inputs['manifests']['weekly']['records'][0]
    row['preflight']['checks']['duplicates'] = {'status': 'held', 'evidence': {'old': 'retained'}}
    entry = evaluate(row, at=now)
    entry['collection'] = 'weekly'
    ledger = {'records': {'weekly:fresh': entry}}
    inputs['lifecycle'] = deepcopy(ledger)
    inputs['lifecycle_policy'] = {}
    inputs['registry'][0]['manifest_url'] = 'https://example.test/config/weekly_review_manifest.json'
    records = [{'collection': 'weekly', 'candidate_id': 'fresh', 'content_sha256': row['content_sha256'],
                'checks': deepcopy(row['preflight']['checks']), 'status': 'held', 'review_ready': False}]
    inputs['preflight_status'] = {'records': records, 'summary': derive(records)}
    for name in ('weekly_review_manifest.json', 'content_review_candidate_lifecycle.json',
                 'content_review_preflight_status.json', 'content_review_worker_status.json'):
        inputs['metadata'].append({'commit': inputs['review_commit'], 'path': 'config/' + name,
                                   'sha': 'c' * 40, 'size': 1, 'sha256': 'd' * 64})
    return now, snapshot, inputs, state, ledger


def call(now, snapshot, inputs, state, ledger, confirmed=None):
    return prepare(snapshot, deepcopy(snapshot) if confirmed is None else confirmed,
                   inputs, ledger, state, 'worker', 'run', 'weekly', 'fresh',
                   observed_heads={'review': 'a' * 40, 'main': 'b' * 40},
                   source_attempts={}, source_progress={}, at=now)


def test_bundle_preserves_prior_evidence_and_reconciles_stage_without_writing():
    now, snapshot, inputs, state, ledger = setup_bundle()
    before = deepcopy((snapshot, inputs, state, ledger))
    result = call(now, snapshot, inputs, state, ledger)
    assert result['status'] == 'prepared' and result['writes'] == 0
    assert result['requires_remote_lease_and_snapshot_recheck'] is True
    assert len(result['files']) == 5 and len(result['new_paths_must_be_absent']) == 1
    manifest = json.loads(result['files']['config/weekly_review_manifest.json'])
    row = manifest['records'][0]
    assert row['decision'] == 'pending'
    assert row['preflight']['checks']['duplicates']['prior_evidence']['evidence'] == {'old': 'retained'}
    status = json.loads(result['files']['config/content_review_preflight_status.json'])
    assert status['records'][0]['checks'] == row['preflight']['checks']
    assert 'duplicates' not in status['records'][0]['blockers']
    assert status['records'][0]['review_ready'] is False
    saved_ledger = json.loads(result['files']['config/content_review_candidate_lifecycle.json'])
    assert saved_ledger['records']['weekly:fresh']['attempts'][-1]['stage'] == 'duplicates'
    saved_state = json.loads(result['files']['config/content_review_worker_status.json'])
    assert saved_state['source_attempts']['weekly']['gate'] == 'duplicates'
    assert saved_state['source_last_progress'] == {}
    receipt = json.loads(result['files'][result['new_paths_must_be_absent'][0]])
    assert receipt['openalex_requests'] == receipt['paid_requests'] == 0
    assert receipt['publication_approved'] is False
    assert (snapshot, inputs, state, ledger) == before


def test_stale_snapshots_or_insufficient_reserve_fail_closed():
    now, snapshot, inputs, state, ledger = setup_bundle()
    changed = deepcopy(snapshot)
    changed['read_evidence']['jobs']['complete'] = False
    with pytest.raises(ValueError, match='Incomplete jobs'):
        call(now, snapshot, inputs, state, ledger, changed)
    state['lease']['expires_at'] = (now + timedelta(seconds=119)).isoformat()
    inputs['worker_state'] = deepcopy(state)
    with pytest.raises(ValueError, match='reserve'):
        call(now, snapshot, inputs, state, ledger)


def test_divergent_stage_evidence_fails_closed():
    now, snapshot, inputs, state, ledger = setup_bundle()
    inputs['preflight_status']['records'][0]['checks'] = {}
    with pytest.raises(ValueError, match='checks disagree'):
        call(now, snapshot, inputs, state, ledger)

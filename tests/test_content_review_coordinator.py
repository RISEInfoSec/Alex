from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from tools.content_review.coordinator import plan
from tools.content_review.d1_reconcile import SnapshotError


def fixture():
    now = datetime(2026, 11, 6, 20, 0, tzinfo=timezone.utc)
    h = 'a' * 64
    sub = {'id': 's', 'user_id': 'owner', 'collection': 'weekly', 'batch': 1,
           'revision': 1, 'accepted': 0, 'rejected': 1, 'payload_hash': 'b' * 64}
    decision = {'id': 'd', 'submission_id': 's', 'user_id': 'owner', 'collection': 'weekly',
                'batch': 1, 'revision': 1, 'candidate_id': 'decided', 'review_number': 1,
                'content_sha256': h, 'decision': 'rejected'}
    snap = {'submissions': [sub], 'decisions': [decision], 'jobs': []}
    snap['read_evidence'] = {k: {'complete': True, 'rows_received': len(snap[k]),
                                  'truncated_values': 0, 'omitted_columns': 0}
                             for k in ('submissions', 'decisions', 'jobs')}
    manifests = {'weekly': {'records': [dict(candidate_id='decided', review_number=1, content_sha256=h),
                                       dict(candidate_id='fresh', review_number=2, content_sha256='c' * 64,
                                            document_type='research_paper', abstract='', decision='pending')]}}
    ledger = {'records': {'weekly:' + c: {'state': 'awaiting_initial_checks', 'first_seen_at': '2026-01-01'}
                          for c in ('decided', 'fresh')}}
    registry = [{'id': 'weekly', 'adapter': 'normalized'}, {'id': 'first', 'adapter': 'normalized'},
                {'id': 'apwg', 'adapter': 'apwg_pending'}, {'id': 'corpus-audit', 'adapter': 'corpus_audit'}]
    state = {'lease': {'owner': 'worker', 'run_id': 'run', 'expires_at': (now + timedelta(minutes=20)).isoformat()},
             'current_run': {'run_id': 'run', 'application_status': 'running',
                             'started_at': now.isoformat(), 'observed_at': now.isoformat()}}
    return now, snap, manifests, ledger, registry, state


def test_plan_covers_registered_routes_without_writes_or_openalex():
    now, snap, manifests, ledger, registry, state = fixture()
    before = deepcopy(manifests)
    result = plan(snap, deepcopy(snap), manifests, ledger, registry, state, 'worker', 'run',
                  source_attempts={}, source_progress={}, at=now)
    assert [x['candidate_id'] for x in result['selected']] == ['fresh']
    assert {x['collection'] for x in result['coverage']} == {'weekly', 'first', 'apwg', 'corpus-audit'}
    assert next(x for x in result['coverage'] if x['collection'] == 'first')['disposition'] == 'manifest_unavailable'
    assert next(x for x in result['coverage'] if x['collection'] == 'apwg')['disposition'] == 'separate_collection_adapter_required'
    assert result['status'] == 'plan_only' and result['writes'] == 0
    assert result['openalex_requests_permitted'] == 0 and result['paid_requests'] == 0
    assert result['snapshot_recheck_required'] and result['lease_readback_required']
    assert manifests == before


def test_stale_lease_heartbeat_or_decision_snapshot_blocks_planning():
    now, snap, manifests, ledger, registry, state = fixture()
    args = (snap, deepcopy(snap), manifests, ledger, registry, state, 'worker', 'run')
    with pytest.raises(ValueError, match='single-writer lease'):
        plan(*args, source_attempts={}, source_progress={}, at=now + timedelta(minutes=21))
    with pytest.raises(ValueError, match='heartbeat'):
        plan(*args, source_attempts={}, source_progress={}, at=now + timedelta(seconds=41))
    changed = deepcopy(snap)
    changed['decisions'][0]['decision'] = 'approved'
    with pytest.raises(SnapshotError, match='changed between reads'):
        plan(snap, changed, manifests, ledger, registry, state, 'worker', 'run',
             source_attempts={}, source_progress={}, at=now)


def test_duplicate_candidate_inventory_fails_closed():
    now, snap, manifests, ledger, registry, state = fixture()
    manifests['weekly']['preflight_records'] = [deepcopy(manifests['weekly']['records'][1])]
    with pytest.raises(ValueError, match='Duplicate candidate'):
        plan(snap, deepcopy(snap), manifests, ledger, registry, state, 'worker', 'run',
             source_attempts={}, source_progress={}, at=now)

from copy import deepcopy
from datetime import datetime, timedelta, timezone

import pytest

from tools.content_review.duplicate_stage import evaluate, propose_checkpoint
from tools.content_review.lifecycle import current_pass
from tools.content_review.manifest_integrity import reviewed_digest


def fixture():
    now = datetime(2026, 11, 6, 20, 0, tzinfo=timezone.utc)
    row = {'candidate_id': 'fresh', 'review_number': 1, 'title': 'New research',
           'authors': 'Author', 'year': 2026, 'doi': '', 'source_url': 'https://example.test/paper',
           'abstract': '', 'document_type': 'research_paper', 'decision': 'pending',
           'preflight': {'checks': {}}}
    row['content_sha256'] = reviewed_digest(row)
    snap = {'submissions': [], 'decisions': [], 'jobs': []}
    snap['read_evidence'] = {k: {'complete': True, 'rows_received': 0, 'truncated_values': 0,
                                  'omitted_columns': 0} for k in ('submissions', 'decisions', 'jobs')}
    bundle = {'review_commit': 'a' * 40, 'main_commit': 'b' * 40,
              'registry': [{'id': 'weekly', 'adapter': 'normalized'}, {'id': 'apwg', 'adapter': 'apwg_pending'}],
              'manifests': {'weekly': {'records': [row]}, 'apwg': {'records': [{'title': 'APWG work'}]}},
              'public': [{'title': 'Other work', 'authors': 'Someone', 'year': 2025}],
              'original_queue': [], 'current_queue': [], 'exclusion_keys': set(),
              'metadata': [{'sha256': 'c' * 64}]}
    state = {'lease': {'owner': 'worker', 'run_id': 'run', 'expires_at': (now + timedelta(minutes=10)).isoformat()},
             'current_run': {'run_id': 'run', 'application_status': 'running',
                             'started_at': now.isoformat(), 'observed_at': now.isoformat()}}
    ledger = {'records': {'weekly:fresh': {'state': 'awaiting_initial_checks', 'first_seen_at': '2026-01-01'}}}
    bundle['lifecycle'] = deepcopy(ledger)
    bundle['worker_state'] = deepcopy(state)
    return now, snap, bundle, state, ledger


def run(now, snap, bundle, state, ledger, heads=None):
    return evaluate(snap, deepcopy(snap), bundle, ledger, state, 'worker', 'run', 'weekly', 'fresh',
                    observed_heads=heads or {'review': 'a' * 40, 'main': 'b' * 40},
                    source_attempts={}, source_progress={}, at=now)


def test_duplicate_stage_uses_local_evidence_without_mutating_inputs():
    now, snap, bundle, state, ledger = fixture()
    before = deepcopy(bundle)
    result = run(now, snap, bundle, state, ledger)
    assert result['status'] == 'passed' and result['gate'] == 'duplicates'
    assert result['writes'] == result['provider_requests'] == result['paid_requests'] == 0
    assert result['recheck_d1_heads_and_lease_before_checkpoint'] is True
    assert bundle == before


def test_duplicate_or_exclusion_is_held_without_editorial_mutation():
    now, snap, bundle, state, ledger = fixture()
    bundle['public'].append({'title': 'New research', 'authors': 'Author', 'year': 2026})
    result = run(now, snap, bundle, state, ledger)
    assert result['status'] == 'held' and result['evidence']['matches']
    assert bundle['manifests']['weekly']['records'][0]['decision'] == 'pending'


def test_stale_source_or_unbound_content_cannot_produce_evidence():
    now, snap, bundle, state, ledger = fixture()
    with pytest.raises(ValueError, match='Source heads changed'):
        run(now, snap, bundle, state, ledger, {'review': 'c' * 40, 'main': 'b' * 40})
    bundle['manifests']['weekly']['records'][0]['title'] = 'Changed title'
    with pytest.raises(ValueError, match='does not match its reviewed hash'):
        run(now, snap, bundle, state, ledger)


def test_checkpoint_proposal_preserves_decision_and_is_not_persisted():
    now, snap, bundle, state, ledger = fixture()
    before = deepcopy(bundle)
    result = propose_checkpoint(snap, deepcopy(snap), bundle, ledger, state, 'worker', 'run',
                                'weekly', 'fresh', observed_heads={'review': 'a' * 40, 'main': 'b' * 40},
                                source_attempts={}, source_progress={}, at=now)
    assert result['status'] == 'prepared' and result['writes'] == 0
    row = result['manifest']['records'][0]
    assert row['decision'] == 'pending' and current_pass(row, 'duplicates')
    assert result['requires_remote_lease_and_snapshot_recheck'] is True
    assert bundle == before


def test_duplicate_hold_does_not_propose_a_manifest():
    now, snap, bundle, state, ledger = fixture()
    bundle['public'].append({'title': 'New research', 'authors': 'Author', 'year': 2026})
    result = propose_checkpoint(snap, deepcopy(snap), bundle, ledger, state, 'worker', 'run',
                                'weekly', 'fresh', observed_heads={'review': 'a' * 40, 'main': 'b' * 40},
                                source_attempts={}, source_progress={}, at=now)
    assert result['status'] == 'held' and result['manifest'] is None and result['writes'] == 0


def test_state_must_match_the_verified_commit():
    now, snap, bundle, state, ledger = fixture()
    state['extra'] = 'not in commit'
    with pytest.raises(ValueError, match='differs from the verified source'):
        run(now, snap, bundle, state, ledger)

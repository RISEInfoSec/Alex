from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json

import pytest

from tests.test_content_review_verified_inputs import fixture as git_fixture, git, put
from tools.content_review.heartbeat_evidence import prepare as make_heartbeat
from tools.content_review.manifest_integrity import reviewed_digest
from tools.content_review.soups_intake import prepare, URL
from tools.content_review.soups_intake_guard import prepare as guard
from tools.content_review.verified_inputs import load_inputs


def fixture(repo):
    _, main, _ = git_fixture(repo)
    now = datetime.now(timezone.utc)
    row = {'candidate_id': 'soups-new', 'title': 'Example', 'authors': 'Author', 'year': 2025,
           'doi': '', 'source_url': 'https://example.test/paper', 'abstract': '',
           'document_type': 'research_paper', 'decision': 'pending'}
    row['content_sha256'] = reviewed_digest(row)
    registry = {'collections': [{'id': 'soups', 'adapter': 'soups', 'manifest_url': URL}]}
    state = {'lease': {'owner': 'worker', 'run_id': 'run', 'acquired_at': (now-timedelta(seconds=10)).isoformat(),
                       'expires_at': (now+timedelta(minutes=20)).isoformat()},
             'current_run': {'run_id': 'run', 'application_status': 'running',
                 'started_at': (now-timedelta(seconds=10)).isoformat(),
                 'scheduler': {'id': 'Automation_worker', 'last_run': {'id': 'run', 'recorded_status': 'in_progress'}}}}
    put(repo, 'config/review_console.json', registry)
    put(repo, 'config/soups_review_manifest.json', {'records': [row]})
    put(repo, 'config/content_review_preflight_status.json', {'records': [], 'summary': {}})
    put(repo, 'config/content_review_worker_status.json', state)
    git(repo, 'add', '.');git(repo, 'commit', '-qm', 'SOUPS fixture')
    review = git(repo, 'rev-parse', 'HEAD');branch = git(repo, 'symbolic-ref', '--short', 'HEAD')
    heartbeat = make_heartbeat(state, review, 'worker', 'run', at=now)
    git(repo, 'checkout', '-qb', 'heartbeat')
    put(repo, 'config/content_review_detached_heartbeat.json', heartbeat)
    git(repo, 'add', '.');git(repo, 'commit', '-qm', 'heartbeat')
    hb = git(repo, 'rev-parse', 'HEAD');git(repo, 'checkout', '-q', branch)
    snap = {'submissions': [], 'decisions': [], 'jobs': []}
    snap['read_evidence'] = {k: {'complete': True, 'rows_received': 0, 'truncated_values': 0,
                                 'omitted_columns': 0} for k in ('submissions', 'decisions', 'jobs')}
    inputs = load_inputs(repo, review, main)
    proposal = prepare(snap, deepcopy(snap), inputs, inputs['lifecycle'], state, 'worker', 'run',
        observed_heads={'review': review, 'main': main}, source_attempts={}, source_progress={}, heartbeat=heartbeat, at=now)
    return now, review, main, hb, snap, proposal


def test_guard_binds_exact_files_tree_and_new_receipt_without_writing(tmp_path):
    now, review, main, hb, snap, proposal = fixture(tmp_path)
    result = guard(tmp_path, review, main, hb, snap, deepcopy(snap), 'worker', 'run', proposal, at=now)
    proof, bundle = result['proof'], result['bundle']
    assert proof['kind'] == 'soups_intake' and proof['expected_head'] == review
    assert len(proof['expected_tree']) == 40 and proof['expected_tree'] != proof['base_tree_sha']
    assert set(bundle['files']) == set(proof['base_blobs']) | {proof['new_path']}
    receipt = json.loads(bundle['files'][proof['new_path']])
    assert receipt['candidate_processing'] is False and receipt['publication_approved'] is False
    assert result['writes'] == 0 and result['requires_independent_site_semantic_validation'] is True
    assert git(tmp_path, 'rev-parse', 'HEAD') == review


def test_guard_rejects_tampering_changed_decisions_and_stale_proposals(tmp_path):
    now, review, main, hb, snap, proposal = fixture(tmp_path)
    altered = deepcopy(proposal)
    altered['proposed_manifest']['records'][0]['decision'] = 'approved'
    with pytest.raises(ValueError, match='differs from independently recomputed'):
        guard(tmp_path, review, main, hb, snap, deepcopy(snap), 'worker', 'run', altered, at=now)
    changed = deepcopy(snap);changed['read_evidence']['jobs']['complete'] = False
    with pytest.raises(ValueError, match='Incomplete jobs'):
        guard(tmp_path, review, main, hb, snap, changed, 'worker', 'run', proposal, at=now)
    with pytest.raises(ValueError, match='stale'):
        guard(tmp_path, review, main, hb, snap, deepcopy(snap), 'worker', 'run', proposal, at=now+timedelta(seconds=41))

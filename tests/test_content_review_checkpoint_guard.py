import hashlib
import json
import subprocess
from copy import deepcopy

import pytest

from tests.test_content_review_duplicate_checkpoint import setup_bundle
from tests.test_content_review_verified_inputs import git, put
from tools.content_review.checkpoint_guard import verify
from tools.content_review.duplicate_checkpoint import prepare
from tools.content_review.verified_inputs import _path_blob


def fixture(repo, existing_receipt=False):
    now, snap, inputs, state, ledger = setup_bundle()
    git(repo, 'init', '--quiet')
    path_objects = {
        'config/weekly_review_manifest.json': inputs['manifests']['weekly'],
        'config/content_review_candidate_lifecycle.json': ledger,
        'config/content_review_preflight_status.json': inputs['preflight_status'],
        'config/content_review_worker_status.json': state,
    }
    for path, value in path_objects.items():
        put(repo, path, value)
    put(repo, 'config/content_review_lifecycle_policy.json', inputs['lifecycle_policy'])
    if existing_receipt:
        content_hash = inputs['manifests']['weekly']['records'][0]['content_sha256']
        ident = hashlib.sha256(('run\0weekly:fresh\0' + content_hash).encode()).hexdigest()
        put(repo, 'config/content_review_mechanical_checkpoints/' + ident + '.json', {'preserve': True})
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'source')
    head = git(repo, 'rev-parse', 'HEAD')
    inputs['review_commit'] = head
    inputs['metadata'] = [_path_blob(repo, head, p)[1] for p in path_objects]
    bundle = prepare(snap, deepcopy(snap), inputs, ledger, state, 'worker', 'run', 'weekly', 'fresh',
                     observed_heads={'review': head, 'main': inputs['main_commit']},
                     source_attempts={}, source_progress={}, at=now)
    return head, inputs['main_commit'], bundle


def mutate(bundle, path, f):
    obj = json.loads(bundle['files'][path]); f(obj)
    bundle['files'][path] = json.dumps(obj)


def test_proposed_atomic_bundle_is_bound_to_exact_base_and_new_receipt(tmp_path):
    head, main, bundle = fixture(tmp_path)
    result = verify(tmp_path, head, main, bundle)
    assert result['expected_head'] == head and result['writes'] == 0
    assert result['base_tree_sha'] == git(tmp_path, 'rev-parse', head + '^{tree}')
    assert result['new_path'] == bundle['new_paths_must_be_absent'][0]
    assert set(result['blobs']) == set(bundle['files'])
    assert result['base_blobs'] == bundle['base_blobs']
    assert result['requires_remote_head_d1_and_lease_recheck'] is True


def test_existing_receipt_or_wrong_base_blob_blocks_write(tmp_path):
    head, main, bundle = fixture(tmp_path, existing_receipt=True)
    with pytest.raises(ValueError, match='receipt already exists'):
        verify(tmp_path, head, main, bundle)
    clean = tmp_path / 'clean'; clean.mkdir()
    head, main, bundle = fixture(clean)
    path = 'config/weekly_review_manifest.json'
    bundle['base_blobs'][path]['blob_sha'] = '0' * 40
    with pytest.raises(ValueError, match='base blob differs'):
        verify(clean, head, main, bundle)


def test_unrelated_candidate_changes_and_lost_evidence_are_rejected(tmp_path):
    head, main, bundle = fixture(tmp_path)
    path = 'config/weekly_review_manifest.json'
    changed = deepcopy(bundle)
    mutate(changed, path, lambda o: o['records'][0].update({'title':'unrelated edit'}))
    with pytest.raises(ValueError, match='unrelated manifest'):
        verify(tmp_path, head, main, changed)
    changed = deepcopy(bundle)
    mutate(changed, path, lambda o: o['records'][0]['preflight']['checks']['duplicates'].pop('prior_evidence'))
    with pytest.raises(ValueError, match='Prior duplicate evidence'):
        verify(tmp_path, head, main, changed)


def test_worker_lease_and_other_source_progress_cannot_be_changed(tmp_path):
    head, main, bundle = fixture(tmp_path)
    path = 'config/content_review_worker_status.json'
    changed = deepcopy(bundle)
    mutate(changed, path, lambda o: o['lease'].update({'owner':'another-writer'}))
    with pytest.raises(ValueError, match='unrelated worker state'):
        verify(tmp_path, head, main, changed)
    changed = deepcopy(bundle)
    mutate(changed, path, lambda o: o['source_last_progress'].update({'weekly':{'at':'invented'}}))
    with pytest.raises(ValueError, match='source progress'):
        verify(tmp_path, head, main, changed)


def test_receipt_cannot_claim_provider_or_publication_activity(tmp_path):
    head, main, bundle = fixture(tmp_path)
    receipt = bundle['new_paths_must_be_absent'][0]
    mutate(bundle, receipt, lambda o: o.update({'openalex_requests':1}))
    with pytest.raises(ValueError, match='receipt is invalid'):
        verify(tmp_path, head, main, bundle)


def test_controlled_local_checkpoint_and_competing_writer(tmp_path):
    head, main, bundle = fixture(tmp_path)
    proof = verify(tmp_path, head, main, bundle)
    for path, content in bundle['files'].items():
        put(tmp_path, path, content)
    git(tmp_path, 'add', *bundle['files'])
    tree = git(tmp_path, 'write-tree')
    winner = git(tmp_path, 'commit-tree', tree, '-p', head, '-m', 'synthetic checkpoint')
    competitor = git(tmp_path, 'commit-tree', tree, '-p', head, '-m', 'competing synthetic writer')
    branch = git(tmp_path, 'symbolic-ref', 'HEAD')
    git(tmp_path, 'update-ref', branch, winner, head)
    refused = subprocess.run(['git', '-C', str(tmp_path), 'update-ref', branch, competitor, head],
                             capture_output=True, text=True, check=False)
    assert refused.returncode != 0
    assert git(tmp_path, 'rev-parse', branch) == winner
    assert git(tmp_path, 'rev-parse', winner + '^') == proof['expected_head']
    receipt = proof['new_path']
    assert json.loads(git(tmp_path, 'show', winner + ':' + receipt))['publication_approved'] is False

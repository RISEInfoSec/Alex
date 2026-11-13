import subprocess

import pytest

from tools.content_review.proposed_tree import compute


def git(repo, *args):
    return subprocess.check_output(['git', '-C', str(repo), *args], stderr=subprocess.PIPE).decode().strip()


@pytest.fixture
def repository(tmp_path):
    repo = tmp_path / 'repo'
    repo.mkdir()
    git(repo, 'init', '-q')
    git(repo, 'config', 'user.email', 'test@example.test')
    git(repo, 'config', 'user.name', 'Test')
    (repo / 'config').mkdir()
    (repo / 'config' / 'state.json').write_text('{"old":true}\n')
    (repo / 'config' / 'unrelated.json').write_text('{"keep":true}\n')
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'Base')
    head = git(repo, 'rev-parse', 'HEAD')
    blob = git(repo, 'rev-parse', head + ':config/state.json')
    return repo, head, {'config/state.json': {'path': 'config/state.json', 'commit': head, 'blob_sha': blob}}


def test_tree_matches_independent_git_index_without_changing_worktree(repository):
    repo, head, bases = repository
    files = {'config/state.json': '{"text":"é"}\n', 'config/receipts/run.json': '{"run":1}\n'}
    result = compute(repo, head, files, bases, ['config/receipts/run.json'])
    assert result['writes'] == 0 and result['requires_semantic_guard_and_live_recheck'] is True
    assert git(repo, 'status', '--porcelain') == ''
    assert git(repo, 'rev-parse', 'HEAD') == head
    for path, text in files.items():
        target = repo / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    git(repo, 'add', 'config')
    assert result['expected_tree'] == git(repo, 'write-tree')
    assert result['blob_shas']['config/state.json'] == git(repo, 'rev-parse', ':config/state.json')


def test_changed_base_existing_receipt_and_unbounded_payload_fail_closed(repository):
    repo, head, bases = repository
    with pytest.raises(ValueError, match='base blob differs'):
        compute(repo, head, {'config/state.json': '{}'},
                {'config/state.json': {**bases['config/state.json'], 'blob_sha': 'f' * 40}}, [])
    with pytest.raises(ValueError, match='already exists'):
        compute(repo, head, {'config/state.json': '{}'}, {}, ['config/state.json'])
    with pytest.raises(ValueError, match='bounded size'):
        compute(repo, head, {'config/state.json': 'x' * (12 * 1024 * 1024 + 1)}, bases, [])
    with pytest.raises(ValueError, match='path or content'):
        compute(repo, head, {'config/../escape.json': '{}'}, {}, ['config/../escape.json'])

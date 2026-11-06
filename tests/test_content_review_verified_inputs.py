import hashlib
import json
import subprocess

import pytest

from tools.content_review.verified_inputs import load_inputs


def git(repo, *args, data=None):
    return subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Test',
                           '-c', 'user.email=test@example.test', *args], input=data,
                          text=True, capture_output=True, check=True).stdout.strip()


def put(repo, path, value):
    dest = repo / path
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(value if isinstance(value, str) else json.dumps(value))


def fixture(repo):
    git(repo, 'init', '--quiet')
    old = 'candidate_id,title\n1,First\n2,Second\n'
    old_sha = git(repo, 'hash-object', '-w', '--stdin', data=old)
    put(repo, 'data/papers.json', [{'title': 'Published'}])
    put(repo, 'data/review_queue.csv', 'candidate_id,title\n3,Current\n')
    put(repo, 'config/corpus_exclusions.json', {'schema_version': 1, 'records': [
        {'decision': 'rejected', 'submission_id': 's', 'reviewed_content_sha256': 'a' * 64,
         'title': 'Excluded', 'year': 2026}]})
    put(repo, 'config/apwg_pending_review.json', {'records': []})
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'main')
    main = git(repo, 'rev-parse', 'HEAD')
    registry = {'collections': [
        {'id': 'weekly', 'adapter': 'normalized', 'manifest_url':
         'https://raw.githubusercontent.com/RISEInfoSec/Alex/codex/soups-corpus-review/config/weekly_review_manifest.json'},
        {'id': 'apwg', 'adapter': 'apwg_pending', 'manifest_url':
         'https://raw.githubusercontent.com/RISEInfoSec/Alex/main/config/apwg_pending_review.json'}]}
    inventory = {'source_blob_sha': old_sha, 'source_sha256': hashlib.sha256(old.encode()).hexdigest(),
                 'raw_records': 2, 'records': [{'row': n, 'upstream_id': str(n+1),
                                                  'content_sha256': 'b' * 64} for n in range(2)]}
    put(repo, 'config/review_console.json', registry)
    put(repo, 'config/weekly_source_inventory.json', inventory)
    put(repo, 'config/weekly_review_manifest.json', {'records': [], 'preflight_records': []})
    git(repo, 'add', '.')
    git(repo, 'commit', '-qm', 'review')
    return git(repo, 'rev-parse', 'HEAD'), main, inventory


def test_inputs_come_from_exact_commits_and_preserve_old_and_new_upstream(tmp_path):
    review, main, _ = fixture(tmp_path)
    # A changed working tree must not replace committed source evidence.
    put(tmp_path, 'data/papers.json', [])
    result = load_inputs(tmp_path, review, main)
    assert result['counts'] == {'collections': 2, 'public': 1, 'exclusions': 1,
                                'original_queue': 2, 'current_queue': 1}
    assert [x['candidate_id'] for x in result['original_queue']] == ['1', '2']
    assert result['current_queue'][0]['candidate_id'] == '3'
    assert 'title-year:excluded|2026' in result['exclusion_keys']


def test_retained_original_queue_digest_and_row_identity_are_required(tmp_path):
    review, main, inventory = fixture(tmp_path)
    inventory['records'][1]['upstream_id'] = 'wrong'
    put(tmp_path, 'config/weekly_source_inventory.json', inventory)
    git(tmp_path, 'add', 'config/weekly_source_inventory.json')
    git(tmp_path, 'commit', '-qm', 'bad inventory')
    changed = git(tmp_path, 'rev-parse', 'HEAD')
    with pytest.raises(ValueError, match='identity mismatch'):
        load_inputs(tmp_path, changed, main)
    inventory['records'][1]['upstream_id'] = '2'
    inventory['source_sha256'] = '0' * 64
    put(tmp_path, 'config/weekly_source_inventory.json', inventory)
    git(tmp_path, 'add', 'config/weekly_source_inventory.json')
    git(tmp_path, 'commit', '-qm', 'bad digest')
    with pytest.raises(ValueError, match='digest mismatch'):
        load_inputs(tmp_path, git(tmp_path, 'rev-parse', 'HEAD'), main)


def test_missing_manifest_or_empty_public_corpus_fails_closed(tmp_path):
    review, main, _ = fixture(tmp_path)
    with pytest.raises(ValueError):
        load_inputs(tmp_path, review, '0' * 40)
    put(tmp_path, 'data/papers.json', [])
    git(tmp_path, 'add', 'data/papers.json')
    git(tmp_path, 'commit', '-qm', 'empty corpus')
    with pytest.raises(ValueError, match='Invalid public corpus'):
        load_inputs(tmp_path, review, git(tmp_path, 'rev-parse', 'HEAD'))

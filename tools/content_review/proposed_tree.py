"""Compute a prospective Git tree without modifying the repository or index.

This helper does not validate the semantic correctness of a checkpoint and is
not a write authorization. The separate checkpoint guard must validate the
proposal, and the caller must still hold the D1 fence, live lease and fresh
source/decision observations before an expected-head GitHub update.
"""
import hashlib
import os
from pathlib import Path
import re
import subprocess
import tempfile

SHA = re.compile(r'^[0-9a-f]{40}$')
PATH = re.compile(r'^config/[a-zA-Z0-9_./-]+\.json$')
LIMIT = 12 * 1024 * 1024


def _git(repo, args, *, env=None, data=None):
    try:
        result = subprocess.run(['git', '-C', str(repo), *args], input=data,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, check=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError('Prospective tree Git operation failed') from exc
    return result.stdout


def compute(repo, head, files, base_blobs, new_paths):
    """Return the full tree and blob IDs for an already guarded proposal."""
    root = Path(repo).resolve()
    if not isinstance(head, str) or not SHA.fullmatch(head):
        raise ValueError('Full immutable base commit required')
    if (not isinstance(files, dict) or not 1 <= len(files) <= 5 or
        not isinstance(base_blobs, dict) or not isinstance(new_paths, list) or len(new_paths) != len(set(new_paths))):
        raise ValueError('Invalid prospective tree inventory')
    if set(files) != set(base_blobs) | set(new_paths) or set(base_blobs) & set(new_paths):
        raise ValueError('Prospective paths differ from verified base inventory')
    raw = {}
    for path, content in files.items():
        if not isinstance(path, str) or not PATH.fullmatch(path) or '..' in path or not isinstance(content, str):
            raise ValueError('Invalid prospective tree path or content')
        try:
            raw[path] = content.encode('utf-8')
        except UnicodeEncodeError as exc:
            raise ValueError('Invalid prospective tree content') from exc
    if sum(map(len, raw.values())) > LIMIT:
        raise ValueError('Prospective tree exceeds bounded size')
    for path in files:
        data = _git(root, ['ls-tree', '-z', head, '--', path])
        if path in new_paths:
            if data:
                raise ValueError('Prospective new path already exists')
            continue
        try:
            header, name = data.rstrip(b'\0').split(b'\t', 1)
            mode, kind, sha = header.decode('ascii').split(' ')
        except (ValueError, UnicodeDecodeError) as exc:
            raise ValueError('Prospective base path is unavailable') from exc
        old = base_blobs[path]
        if (mode != '100644' or kind != 'blob' or name.decode('utf-8') != path or
            not isinstance(old, dict) or old.get('path') != path or old.get('commit') != head or old.get('blob_sha') != sha):
            raise ValueError('Prospective base blob differs from verified input')
    objects = _git(root, ['rev-parse', '--git-path', 'objects']).decode('utf-8').strip()
    objects_path = Path(objects)
    if not objects_path.is_absolute():
        objects_path = root / objects_path
    if not objects_path.is_dir():
        raise ValueError('Repository objects are unavailable')
    with tempfile.TemporaryDirectory(prefix='alex-proposed-tree-') as temporary:
        temporary = Path(temporary)
        (temporary / 'objects').mkdir()
        env = os.environ.copy()
        env.update(GIT_INDEX_FILE=str(temporary / 'index'), GIT_OBJECT_DIRECTORY=str(temporary / 'objects'),
                   GIT_ALTERNATE_OBJECT_DIRECTORIES=str(objects_path.resolve()))
        _git(root, ['read-tree', head], env=env)
        blob_ids = {}
        for path in sorted(raw):
            content = raw[path]
            sha = _git(root, ['hash-object', '-w', '--stdin'], env=env, data=content).decode('ascii').strip()
            expected = hashlib.sha1(b'blob ' + str(len(content)).encode('ascii') + b'\0' + content).hexdigest()
            if sha != expected:
                raise ValueError('Prospective blob hash mismatch')
            _git(root, ['update-index', '--add', '--cacheinfo', '100644,' + sha + ',' + path], env=env)
            blob_ids[path] = sha
        tree = _git(root, ['write-tree'], env=env).decode('ascii').strip()
        if not SHA.fullmatch(tree):
            raise ValueError('Prospective tree identity is invalid')
        return {'expected_tree': tree, 'blob_shas': blob_ids, 'writes': 0,
                'requires_semantic_guard_and_live_recheck': True}


def bind_guarded(repo, head, files, base_blobs, new_path, blobs):
    """Bind already semantically validated files to their complete Git tree."""
    if not isinstance(blobs, dict) or set(blobs) != set(files):
        raise ValueError('Guarded blob inventory is incomplete')
    result = compute(repo, head, files, base_blobs, [new_path])
    if any(not isinstance(blobs[path], dict) or blobs[path].get('blob_sha') != sha
           for path, sha in result['blob_shas'].items()):
        raise ValueError('Guarded blobs differ from the prospective tree')
    return result['expected_tree']

"""Load complete review inputs from immutable local Git objects, without network.

The caller must independently obtain and recheck current branch heads. This
module does not accept mutable working-tree files as evidence and performs no
provider requests, candidate writes or publication.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import subprocess
from pathlib import PurePosixPath

from alex.editorial_exclusions import exclusion_keys
from tools.content_review.snapshot_integrity import verify_bytes

SHA = re.compile(r'^[0-9a-f]{40}$')
SHA256 = re.compile(r'^[0-9a-f]{64}$')
MAX_BLOB_BYTES = 32 * 1024 * 1024
MAX_CSV_ROWS = 50000


def _git(repo, *args):
    result = subprocess.run(['git', '-C', str(repo), *args], capture_output=True, check=False)
    if result.returncode:
        raise ValueError('Required immutable Git object is unavailable')
    return result.stdout


def _blob(repo, sha):
    if not isinstance(sha, str) or not SHA.fullmatch(sha):
        raise ValueError('Invalid immutable blob identity')
    try:
        size = int(_git(repo, 'cat-file', '-s', sha))
    except ValueError as exc:
        raise ValueError('Invalid immutable blob size') from exc
    if size < 0 or size > MAX_BLOB_BYTES:
        raise ValueError('Immutable blob exceeds the bounded input size')
    raw = _git(repo, 'cat-file', 'blob', sha)
    proof = verify_bytes(raw, sha, size)
    return raw, proof


def _path_blob(repo, commit, path):
    if not isinstance(commit, str) or not SHA.fullmatch(commit):
        raise ValueError('A full immutable commit identity is required')
    p = PurePosixPath(path)
    if p.is_absolute() or '..' in p.parts or not re.fullmatch(r'[a-zA-Z0-9_./-]+', path):
        raise ValueError('Invalid repository-relative input path')
    entry = _git(repo, 'ls-tree', '-z', commit, '--', path)
    try:
        header, returned = entry.rstrip(b'\0').split(b'\t', 1)
        mode, kind, sha = header.decode('ascii').split(' ')
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError('Required committed input is missing') from exc
    if mode != '100644' or kind != 'blob' or returned.decode('utf-8') != path:
        raise ValueError('Required committed input is not a regular file')
    raw, proof = _blob(repo, sha)
    return raw, {'commit': commit, 'path': path, **proof}


def _json(raw):
    try:
        return json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError('Invalid complete JSON input') from exc


def _csv(raw):
    try:
        text = raw.decode('utf-8-sig')
        previous = csv.field_size_limit()
        try:
            csv.field_size_limit(MAX_BLOB_BYTES)
            reader = csv.DictReader(io.StringIO(text, newline=''))
            if (not reader.fieldnames or 'candidate_id' not in reader.fieldnames
                or any(not name for name in reader.fieldnames)
                or len(reader.fieldnames) != len(set(reader.fieldnames))):
                raise ValueError('Upstream CSV lacks candidate identity')
            rows = []
            for row in reader:
                if len(rows) >= MAX_CSV_ROWS or None in row:
                    raise ValueError('Invalid or oversized upstream CSV')
                rows.append(row)
        finally:
            csv.field_size_limit(previous)
        return rows
    except (UnicodeDecodeError, csv.Error) as exc:
        raise ValueError('Invalid complete upstream CSV') from exc


def load_inputs(repo, review_commit, main_commit):
    """Load all registered manifests, public corpus, exclusions and both queues.

    Return full data only in memory. The caller must recheck both remote heads
    and D1 while holding the current lease immediately before checkpointing.
    """
    metadata = {}
    def read(commit, path):
        raw, proof = _path_blob(repo, commit, path)
        metadata[(commit, path)] = proof
        return raw

    registry = _json(read(review_commit, 'config/review_console.json'))
    collections = registry.get('collections') if isinstance(registry, dict) else None
    if not isinstance(collections, list) or not collections:
        raise ValueError('Complete collection registry required')
    lifecycle = _json(read(review_commit, 'config/content_review_candidate_lifecycle.json'))
    lifecycle_policy = _json(read(review_commit, 'config/content_review_lifecycle_policy.json'))
    preflight_status = _json(read(review_commit, 'config/content_review_preflight_status.json'))
    worker_state = _json(read(review_commit, 'config/content_review_worker_status.json'))
    defects = _json(read(review_commit, 'config/content_review_defects.json'))
    workflow = _json(read(review_commit, 'config/content_review_workflow.json'))
    material_policy = _json(read(review_commit, 'config/content_review_material_policy.json'))
    if (not isinstance(lifecycle, dict) or not isinstance(lifecycle.get('records'), dict)
        or not isinstance(lifecycle_policy, dict) or not isinstance(preflight_status, dict)
        or not isinstance(preflight_status.get('records'), list)
        or not isinstance(worker_state, dict) or not isinstance(defects, dict)
        or not isinstance(defects.get('defects'), list) or not isinstance(workflow, dict)
        or not isinstance(material_policy, dict)):
        raise ValueError('Incomplete coordinator policy or state')
    manifests = {}
    for entry in collections:
        if (not isinstance(entry, dict) or not isinstance(entry.get('id'), str)
            or not re.fullmatch(r'[a-z][a-z0-9-]{0,40}', entry['id']) or entry['id'] in manifests
            or entry.get('adapter') not in ('soups', 'apwg_pending', 'normalized', 'corpus_audit')):
            raise ValueError('Invalid or duplicate registered collection')
        url = entry.get('manifest_url') or ''
        root = 'https://raw.githubusercontent.com/RISEInfoSec/Alex/'
        if url.startswith(root + 'main/config/'):
            commit, name = main_commit, url[len(root + 'main/config/'):]
        elif url.startswith(root + 'codex/soups-corpus-review/config/'):
            commit, name = review_commit, url[len(root + 'codex/soups-corpus-review/config/'):]
        else:
            raise ValueError('Unsupported collection manifest source')
        if not re.fullmatch(r'[a-zA-Z0-9_-]+\.json', name):
            raise ValueError('Invalid collection manifest name')
        manifest = _json(read(commit, 'config/' + name))
        if not isinstance(manifest, dict) or not isinstance(manifest.get('records'), list):
            raise ValueError('Invalid collection manifest')
        if 'preflight_records' in manifest and not isinstance(manifest['preflight_records'], list):
            raise ValueError('Invalid preflight inventory')
        manifests[entry['id']] = manifest

    public = _json(read(main_commit, 'data/papers.json'))
    if not isinstance(public, list) or not public or not all(isinstance(x, dict) for x in public):
        raise ValueError('Invalid public corpus')
    exclusions = _json(read(main_commit, 'config/corpus_exclusions.json'))
    if not isinstance(exclusions, dict) or exclusions.get('schema_version') != 1 or not isinstance(exclusions.get('records'), list):
        raise ValueError('Invalid editorial exclusions')
    excluded = set()
    for row in exclusions['records']:
        if (not isinstance(row, dict) or row.get('decision') != 'rejected' or not row.get('submission_id')
            or not isinstance(row.get('reviewed_content_sha256'), str) or not SHA256.fullmatch(row['reviewed_content_sha256'])):
            raise ValueError('Exclusion lacks a content-bound human decision')
        keys = exclusion_keys(row)
        if not keys:
            raise ValueError('Exclusion lacks a bibliographic identity')
        excluded.update(keys)
    current_queue = _csv(read(main_commit, 'data/review_queue.csv'))
    inventory = _json(read(review_commit, 'config/weekly_source_inventory.json'))
    if not isinstance(inventory, dict) or not isinstance(inventory.get('records'), list):
        raise ValueError('Invalid retained upstream inventory')
    old_raw, old_proof = _blob(repo, inventory.get('source_blob_sha'))
    if hashlib.sha256(old_raw).hexdigest() != inventory.get('source_sha256'):
        raise ValueError('Retained upstream digest mismatch')
    old_queue = _csv(old_raw)
    if inventory.get('raw_records') != len(old_queue) or len(inventory['records']) != len(old_queue):
        raise ValueError('Retained upstream inventory count mismatch')
    for index, record in enumerate(inventory['records']):
        if (not isinstance(record, dict) or record.get('row') != index
            or record.get('upstream_id') != str(old_queue[index].get('candidate_id'))
            or not isinstance(record.get('content_sha256'), str) or not SHA256.fullmatch(record['content_sha256'])):
            raise ValueError('Retained upstream identity mismatch')
    return {'registry': collections, 'manifests': manifests, 'public': public,
            'exclusion_keys': excluded, 'original_queue': old_queue, 'current_queue': current_queue,
            'lifecycle': lifecycle, 'worker_state': worker_state, 'defects': defects,
            'lifecycle_policy': lifecycle_policy, 'preflight_status': preflight_status,
            'workflow': workflow, 'material_policy': material_policy,
            'metadata': list(metadata.values()) + [old_proof],
            'review_commit': review_commit, 'main_commit': main_commit,
            'counts': {'collections': len(collections), 'public': len(public),
                       'exclusions': len(exclusions['records']), 'original_queue': len(old_queue),
                       'current_queue': len(current_queue)}}

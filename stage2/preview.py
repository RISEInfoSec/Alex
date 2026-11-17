"""Publish complete private preview generations through one atomic pointer."""
from __future__ import annotations

import csv
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import uuid

from stage1.engine import canonical, digest


def write_file(path, data):
    with path.open('xb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def fsync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def publish(store, directory, *, after_generation=None):
    out = Path(directory).resolve()
    if out == store.path.parent or store.path.is_relative_to(out):
        raise ValueError('preview_must_exclude_private_database')
    out.mkdir(parents=True, exist_ok=True)
    with (out / '.projection.lock').open('a+b') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _publish(store, out, after_generation=after_generation)


def _publish(store, directory, *, after_generation=None):
    out = Path(directory).resolve()
    if out == store.path.parent or store.path.is_relative_to(out):
        raise ValueError('preview_must_exclude_private_database')
    with store.transaction():
        papers = [json.loads(r[0]) for r in store.db.execute('SELECT record FROM publications ORDER BY candidate_id')]
        # Only public bibliographic fields leave the private authority. Raw
        # response bodies, check evidence, actors and reasons stay private.
        fields = ('id', 'title', 'authors', 'year', 'doi', 'venue', 'source_url', 'abstract',
                  'publication_date', 'publication_date_precision', 'publication_date_source',
                  'publication_date_status', 'publication_date_basis', 'collection', 'collection_source')
        papers = [{k: row[k] for k in fields if k in row} for row in papers]
        database_digest = digest(papers)
    generation = database_digest
    out.mkdir(parents=True, exist_ok=True)
    generations = out / 'generations'
    generations.mkdir(exist_ok=True)
    final = generations / generation
    temporary = generations / ('.pending-' + uuid.uuid4().hex)
    stream = io.StringIO(newline='')
    columns = sorted({k for row in papers for k in row}) or ['id']
    writer = csv.DictWriter(stream, fieldnames=columns)
    writer.writeheader()
    writer.writerows(papers)
    documents = {'papers.json': (json.dumps(papers, ensure_ascii=False, indent=2) + '\n').encode(),
                 'papers.csv': stream.getvalue().encode(),
                 'collections.json': (json.dumps({name: [p['id'] for p in papers if p.get('collection') == name]
                                                  for name in sorted({p.get('collection', '') for p in papers})}, indent=2) + '\n').encode()}
    manifest = {'generation': generation, 'count': len(papers),
                'files': {name: hashlib.sha256(data).hexdigest() for name, data in documents.items()}}
    if not final.exists():
        temporary.mkdir()
        try:
            for name, data in documents.items():
                write_file(temporary / name, data)
            write_file(temporary / 'manifest.json', (canonical(manifest) + '\n').encode())
            fsync_directory(temporary)
            os.replace(temporary, final)
            fsync_directory(generations)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    else:
        actual = json.loads((final / 'manifest.json').read_text())
        if actual != manifest or any(hashlib.sha256((final / n).read_bytes()).hexdigest() != h for n, h in manifest['files'].items()):
            raise ValueError('existing_preview_generation_corrupt')
    if after_generation:
        after_generation(final)
    pending = out / ('.current-' + uuid.uuid4().hex)
    write_file(pending, (canonical(manifest) + '\n').encode())
    os.replace(pending, out / 'current.json')
    fsync_directory(out)
    return manifest


def read(directory):
    out = Path(directory).resolve()
    manifest = json.loads((out / 'current.json').read_text())
    generation = manifest['generation']
    if len(generation) != 64 or any(c not in '0123456789abcdef' for c in generation):
        raise ValueError('invalid_preview_generation')
    folder = out / 'generations' / generation
    if json.loads((folder / 'manifest.json').read_text()) != manifest:
        raise ValueError('preview_manifest_mismatch')
    for name, expected in manifest['files'].items():
        if name not in ('papers.json', 'papers.csv', 'collections.json'):
            raise ValueError('unexpected_preview_file')
        if hashlib.sha256((folder / name).read_bytes()).hexdigest() != expected:
            raise ValueError('preview_file_hash_mismatch')
    papers = json.loads((folder / 'papers.json').read_text())
    if len(papers) != manifest['count'] or digest(papers) != generation:
        raise ValueError('preview_projection_mismatch')
    return papers

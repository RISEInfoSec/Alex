"""Prepare an isolated coordinator checkout using the verified recovery archive."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile

HERE = Path(__file__).resolve().parent
BASE = Path('/workspace/work/preservation/codex_soups-corpus-review')
if '.pyz' not in __file__:
    sys.path[:0] = [str(HERE), str(BASE)]
from tools.content_review.github_read_objects import (REFS, blob, commit, exists, git,
                                                     identity, refs, save, trees_from_entries, hydrate_checkout)


def setup(repo, archive=None, proof=None):
    os.umask(0o077)
    marker=repo/'.git'/'alex-weekly-source-read-cache'
    if not marker.exists():
        if repo.exists() and any(repo.iterdir()):
            raise ValueError('A new or previously initialized coordinator cache is required')
        repo.mkdir(parents=True,exist_ok=True)
        git(repo,'init','-q')
        git(repo,'remote','add','origin','https://github.com/RISEInfoSec/Alex.git')
        marker.write_text('RISEInfoSec/Alex read-only working copy\n')
    if archive and proof and not (repo/'.git'/'alex-seed-complete').exists():
        with archive.open('rb') as fp:
            if hashlib.file_digest(fp,'sha256').hexdigest() != json.loads(proof.read_bytes())['sha256']:
                raise ValueError('Recovery archive checksum differs')
        with tarfile.open(archive, 'r|gz') as stream:
            for entry in stream:
                data=stream.extractfile(entry).read()
                if entry.name.startswith('blobs/'):
                    sha=entry.name[6:]
                    if not exists(repo,sha):save(repo,'blob',sha,data)
                elif entry.name.startswith('refs/'):
                    meta=json.loads(data)
                    trees_from_entries(repo,meta['tree'],meta['entries'])
        (repo/'.git'/'alex-seed-complete').touch()
    heads=refs()
    for head in heads.values():commit(repo,head)
    if archive and proof:
        hydrate_checkout(repo,heads[REFS[0]])
    # Only these files are used as local inputs by source_handoff. The rest of
    # the coordinator reads immutable objects. Never check out or modify user work.
    review=heads[REFS[0]]
    for path in ('config/weekly_review_manifest.json','config/content_review_candidate_lifecycle.json'):
        oid=git(repo,'rev-parse',review+':'+path).decode().strip()
        blob(repo,oid)
        value=git(repo,'cat-file','blob',oid)
        if identity('blob',value)!=oid:raise ValueError('Working input hash differs')
        dest=repo/path;dest.parent.mkdir(parents=True,exist_ok=True)
        tmp=dest.with_suffix('.tmp');tmp.write_bytes(value);tmp.replace(dest)
    return heads


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--repo',type=Path,required=True)
    args=parser.parse_args()
    print(json.dumps(setup(args.repo,HERE.parent/'alex-review-recovery.tar.gz',HERE.parent/'git-backup.json')))

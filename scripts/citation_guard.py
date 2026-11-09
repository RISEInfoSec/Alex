"""Fence citation attempts in pipeline state; never automatically replay a partial run."""
from __future__ import annotations
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path


def _sha(path: Path) -> str:
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):
            digest.update(chunk)
    return digest.hexdigest()


def _digest(payload):
    return hashlib.sha256(json.dumps(payload,sort_keys=True,separators=(',',':')).encode()).hexdigest()


def _read(path):
    try:
        data=json.loads(path.read_text(encoding='utf-8'))
        checksum=data.pop('sha256')
        if checksum!=_digest(data) or data.get('schema_version')!=1:
            raise ValueError
        return data
    except (OSError,ValueError,KeyError,TypeError,AttributeError):
        raise RuntimeError('Citation guard invalid; reconcile before requests') from None


def _write(path,payload):
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=None
    try:
        with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,prefix='.citation-guard-',suffix='.tmp',delete=False) as stream:
            tmp=Path(stream.name)
            json.dump({**payload,'sha256':_digest(payload)},stream,sort_keys=True)
            stream.write('\n');stream.flush();os.fsync(stream.fileno())
        os.replace(tmp,path)
    finally:
        if tmp is not None: tmp.unlink(missing_ok=True)


def _identity():
    run=os.getenv('GITHUB_RUN_ID','');attempt=os.getenv('GITHUB_RUN_ATTEMPT','')
    if not re.fullmatch(r'[0-9]{1,30}',run) or not re.fullmatch(r'[0-9]{1,10}',attempt):
        raise RuntimeError('Citation run identity unavailable; no requests allowed')
    return run,attempt


def begin(root: Path):
    guard=root/'data/citation_run_guard.json';source=root/'data/discovery_candidates.csv'
    run,attempt=_identity()
    if not source.is_file(): raise RuntimeError('Citation input unavailable; no requests allowed')
    if not guard.is_file():
        raise RuntimeError('Citation guard absent; reconcile prior attempts before requests')
    previous=_read(guard)
    if previous.get('status')!='complete' or previous.get('output_sha256')!=_sha(source):
        raise RuntimeError('Prior citation attempt incomplete or unverified; reconcile before requests')
    _write(guard,{'schema_version':1,'status':'started','run_id':run,'run_attempt':attempt,'input_sha256':_sha(source)})


def _verified_evidence(root: Path, input_sha: str, output_sha: str):
    files=list((root/'data').glob('citation_response_evidence-*.jsonl'))
    if len(files)!=1:
        raise RuntimeError('Citation response evidence missing or ambiguous; reconcile')
    try:
        with files[0].open(encoding='utf-8') as stream:
            records=[]
            for line in stream:
                if not line.endswith('\n'): raise ValueError
                records.append(json.loads(line))
        if len(records)<2:
            raise ValueError
        first,last=records[0],records[-1]
        if (first.get('event')!='begin' or first.get('schema_version')!=1
                or first.get('replay_allowed') is not False
                or first.get('context',{}).get('input_sha256')!=input_sha
                or last.get('event')!='prepared' or last.get('output_sha256')!=output_sha):
            raise ValueError
        for record in records[1:-1]:
            response=record.get('response')
            serialized=json.dumps(response,ensure_ascii=False,sort_keys=True)
            if (record.get('event')!='response'
                    or not re.fullmatch(r'[0-9a-f]{64}',str(record.get('request_sha256','')))
                    or hashlib.sha256(serialized.encode()).hexdigest()!=record.get('sha256')):
                raise ValueError
        return files[0].name,_sha(files[0])
    except (OSError,ValueError,TypeError,AttributeError):
        raise RuntimeError('Citation response evidence invalid; reconcile') from None


def complete(root: Path):
    guard=root/'data/citation_run_guard.json';source=root/'data/discovery_candidates.csv'
    run,attempt=_identity();previous=_read(guard)
    if (previous.get('status')!='started' or previous.get('run_id')!=run
            or previous.get('run_attempt')!=attempt or not source.is_file()):
        raise RuntimeError('Citation guard does not match this run; reconcile')
    output_sha=_sha(source)
    evidence_name,evidence_sha=_verified_evidence(root,previous['input_sha256'],output_sha)
    _write(guard,{**previous,'status':'complete','output_sha256':output_sha,
                  'evidence_name':evidence_name,'evidence_sha256':evidence_sha})


if __name__=='__main__':
    import sys
    if len(sys.argv)!=2 or sys.argv[1] not in ('begin','complete'):
        raise SystemExit('Usage: citation_guard.py begin|complete')
    try:
        (begin if sys.argv[1]=='begin' else complete)(Path.cwd())
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from None

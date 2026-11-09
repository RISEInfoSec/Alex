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


def _verified_discovery_transition(root: Path, previous_sha: str, current_sha: str, run: str, attempt: str):
    try:
        recovery=json.loads((root/'data/discovery_recovery_receipt.json').read_text(encoding='utf-8'))
        receipt_path=root/'data/discovery_run_receipt.json'
        raw=receipt_path.read_bytes();receipt=json.loads(raw)
        passes=recovery.get('passes')
        if not isinstance(passes,list) or not passes:
            return False
        last=passes[-1]
        return (recovery.get('schema_version')==1 and recovery.get('status')=='complete'
                and recovery.get('run_id')==f'{run}:{attempt}'
                and recovery.get('starting_candidates_sha256')==previous_sha
                and recovery.get('final_candidates_sha256')==current_sha
                and last.get('status')=='complete' and last.get('returncode')==0
                and last.get('receipt_sha256')==hashlib.sha256(raw).hexdigest()
                and last.get('pass_id')==receipt.get('orchestration_pass_id')
                and receipt.get('status')=='complete' and receipt.get('deferred_tasks')=={}
                and last.get('receipt')==receipt)
    except (OSError,ValueError,TypeError,AttributeError,KeyError):
        return False


def begin(root: Path):
    guard=root/'data/citation_run_guard.json';source=root/'data/discovery_candidates.csv'
    if (root/'data/.citation_guard_ack.json').exists():
        raise RuntimeError('Prior citation acknowledgement present; reconcile before requests')
    run,attempt=_identity()
    if not source.is_file(): raise RuntimeError('Citation input unavailable; no requests allowed')
    if not guard.is_file():
        raise RuntimeError('Citation guard absent; reconcile prior attempts before requests')
    previous=_read(guard)
    current_sha=_sha(source)
    prior_sha=previous.get('output_sha256')
    if (previous.get('status')!='complete'
            or not isinstance(prior_sha,str) or not re.fullmatch(r'[0-9a-f]{64}',prior_sha)
            or (prior_sha!=current_sha and not _verified_discovery_transition(root,prior_sha,current_sha,run,attempt))):
        raise RuntimeError('Prior citation attempt incomplete or unverified; reconcile before requests')
    _write(guard,{'schema_version':1,'status':'started','run_id':run,'run_attempt':attempt,'input_sha256':current_sha})


def acknowledge(root: Path):
    guard=root/'data/citation_run_guard.json';source=root/'data/discovery_candidates.csv'
    run,attempt=_identity();record=_read(guard)
    if (record.get('status')!='started' or record.get('run_id')!=run
            or record.get('run_attempt')!=attempt or not source.is_file()
            or record.get('input_sha256')!=_sha(source)):
        raise RuntimeError('Citation fence does not match this input; reconcile')
    ack=root/'data/.citation_guard_ack.json'
    if ack.exists(): raise RuntimeError('Citation acknowledgement already exists; reconcile')
    _write(ack,{'schema_version':1,'status':'acknowledged','run_id':run,'run_attempt':attempt,
                'guard_sha256':_sha(guard),'input_sha256':record['input_sha256']})


def _verify_ack(root: Path, record):
    run,attempt=_identity();guard=root/'data/citation_run_guard.json'
    ack=_read(root/'data/.citation_guard_ack.json')
    return (ack.get('status')=='acknowledged' and ack.get('run_id')==run
            and ack.get('run_attempt')==attempt and ack.get('guard_sha256')==_sha(guard)
            and ack.get('input_sha256')==record.get('input_sha256'))


def verify_start(root: Path, expected_sha: str):
    run,attempt=_identity();record=_read(root/'data/citation_run_guard.json')
    if (record.get('status')!='started' or record.get('run_id')!=run
            or record.get('run_attempt')!=attempt or record.get('input_sha256')!=expected_sha
            or not _verify_ack(root,record)):
        raise RuntimeError('Citation fence not acknowledged for this input; reconcile')


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
            or previous.get('run_attempt')!=attempt or not source.is_file()
            or not _verify_ack(root,previous)):
        raise RuntimeError('Citation guard does not match this run; reconcile')
    output_sha=_sha(source)
    evidence_name,evidence_sha=_verified_evidence(root,previous['input_sha256'],output_sha)
    _write(guard,{**previous,'status':'complete','output_sha256':output_sha,
                  'evidence_name':evidence_name,'evidence_sha256':evidence_sha})
    (root/'data/.citation_guard_ack.json').unlink()


if __name__=='__main__':
    import sys
    if len(sys.argv)!=2 or sys.argv[1] not in ('begin','acknowledge','complete'):
        raise SystemExit('Usage: citation_guard.py begin|acknowledge|complete')
    try:
        {'begin':begin,'acknowledge':acknowledge,'complete':complete}[sys.argv[1]](Path.cwd())
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from None

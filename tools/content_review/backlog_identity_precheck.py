"""Filter unsafe backlog identities before the independent Site re-audit.

Inputs are immutable verified repository data; this read-only precheck cannot
authorize a write or pass a gate. Unsupported and possible matches remain held.
"""
import json
from pathlib import Path
import subprocess

from tools.content_review.verified_inputs import _path_blob

FIELDS=('title','doi','source_url','link')
MAX_INPUT=32*1024*1024


def inspect(repo,inputs,collection,candidate_id):
    manifests=inputs['manifests'];manifest=manifests.get(collection)
    if not isinstance(manifest,dict):raise ValueError('Backlog precheck manifest unavailable')
    selected=[x for x in manifest.get('records',[])+manifest.get('preflight_records',[]) if x.get('candidate_id')==candidate_id]
    if len(selected)!=1:raise ValueError('Backlog precheck candidate ambiguous')
    rows=list(inputs['public'])
    for name,source in manifests.items():
        for row in source.get('records',[])+source.get('preflight_records',[]):
            if name==collection and (row.get('candidate_id')==candidate_id or row.get('discovery_identity')==candidate_id):continue
            rows.append(row)
    rows.extend(inputs['original_queue']);rows.extend(inputs['current_queue'])
    raw,_=_path_blob(repo,inputs['main_commit'],'config/corpus_exclusions.json')
    exclusions=json.loads(raw)
    if not isinstance(exclusions,dict) or not isinstance(exclusions.get('records'),list):raise ValueError('Backlog exclusions unavailable')
    rows.extend(exclusions['records'])
    def identity_fields(row):
        if not isinstance(row,dict):raise ValueError('Backlog comparison input invalid')
        return {key:row.get(key) for key in FIELDS}
    payload=json.dumps({'candidate':identity_fields(selected[0]),'comparisons':[identity_fields(x) for x in rows]},
                       ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf8')
    if len(payload)>MAX_INPUT:raise ValueError('Backlog precheck input exceeds bound')
    try:
        result=subprocess.run(['node',str(Path(__file__).with_suffix('.cjs'))],input=payload,capture_output=True,timeout=30,check=False)
    except (OSError,subprocess.SubprocessError) as exc:
        raise ValueError('Backlog precheck unavailable') from exc
    if result.returncode!=0 or result.stdout not in (b'clear',b'held',b'unsupported'):
        raise ValueError('Backlog precheck unavailable')
    return result.stdout.decode('ascii')

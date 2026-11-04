"""Validate complete manifests before a write; never reconstruct connector excerpts."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path

def reviewed_digest(row):
    value={k:row.get(k,'') for k in ('title','authors','year','doi','source_url','abstract','document_type')}
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def validate_hashes(manifest):
    for row in manifest.get('records',[])+manifest.get('preflight_records',[]):
        if row.get('content_sha256') and reviewed_digest(row)!=row['content_sha256']:
            raise ValueError('Current reviewed-content hash mismatch: '+row['candidate_id'])

def parse(content):
    if isinstance(content,bytes):content=content.decode('utf8')
    if re.search(r'\[(?:\.{3})?truncated\]|\d+ chars truncated|\.\.\. \[omitted\]',content,re.I):raise ValueError('Literal connector truncation marker; complete immutable input required')
    data=json.loads(content)
    if not isinstance(data,dict):raise ValueError('Complete manifest object required')
    if not any(k in data for k in ('records','preflight_records')):raise ValueError('Manifest record arrays missing')
    rows=[]
    for field in ('records','preflight_records'):
        value=data.get(field,[])
        if not isinstance(value,list):raise ValueError('Complete record arrays required')
        rows.extend(value)
    if any(not isinstance(r,dict) or not r.get('candidate_id') for r in rows):
        raise ValueError('Candidate identities cannot be omitted')
    ids=[r['candidate_id'] for r in rows]
    if len(ids)!=len(set(ids)):raise ValueError('Duplicate candidate identities')
    return data,{r['candidate_id']:r for r in rows}

def validate_update(before,after,allowed_content_changes=(),allowed_decision_changes=(),allowed_removed_ids=()):
    _,old=parse(before);_,new=parse(after)
    missing=set(old)-set(new)-set(allowed_removed_ids)
    if missing:raise ValueError('Existing identities dropped: '+', '.join(sorted(missing)[:5]))
    for cid in set(old)&set(new):
        if old[cid].get('content_sha256')!=new[cid].get('content_sha256') and cid not in allowed_content_changes:
            versions=new[cid].get('reviewed_content_versions',[])+new[cid].get('integrity_repair_versions',[])
            retained=any(v.get('record')==old[cid] and v.get('content_sha256')==old[cid].get('content_sha256') and v.get('reason') for v in versions)
            if not (retained and old[cid].get('decision','pending') in ('pending','unreviewed') and new[cid].get('decision','pending')==old[cid].get('decision','pending') and reviewed_digest(new[cid])==new[cid].get('content_sha256')):
                raise ValueError('Reviewed content changed without explicit reconciliation: '+cid)
        decision=old[cid].get('decision')
        if decision in ('approved','rejected') and new[cid].get('decision')!=decision and cid not in allowed_decision_changes:
            raise ValueError('Existing decision changed without explicit reconciliation: '+cid)
    return {'old_count':len(old),'new_count':len(new),'preserved_identities':len(set(old)&set(new))}

def write_manifest(path,value):
    path=Path(path);content=json.dumps(value,ensure_ascii=False,indent=2)+'\n'
    parse(content)
    if path.exists():validate_update(path.read_text(),content)
    temporary=path.with_suffix(path.suffix+'.tmp');temporary.write_text(content);temporary.replace(path)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--before');p.add_argument('--after',default='HEAD');a=p.parse_args()
    paths=sorted(Path('config').glob('*_review_manifest.json'))
    for path in paths:
        manifest,_=parse(path.read_bytes())
        if path.stem.removesuffix('_review_manifest') in ('soups','weekly','first','m3aawg','bellingcat','sans'):validate_hashes(manifest)
    if a.before and set(a.before)!={'0'}:
        changed=subprocess.check_output(['git','diff','--name-only',a.before,a.after,'--','config'],text=True).splitlines()
        for name in changed:
            if not name.endswith('_review_manifest.json'):continue
            old=subprocess.run(['git','show',a.before+':'+name],capture_output=True)
            if not Path(name).exists():raise ValueError('Manifest removed: '+name)
            if old.returncode==0:validate_update(old.stdout,Path(name).read_bytes())
    print(json.dumps({'status':'passed','complete_manifests_validated':len(paths)}))

if __name__=='__main__':main()

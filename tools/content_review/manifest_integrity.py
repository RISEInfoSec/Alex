"""Validate complete manifests before a write; never reconstruct connector excerpts."""
from __future__ import annotations
import argparse
import json
import subprocess
from pathlib import Path

def parse(content):
    if isinstance(content,bytes):content=content.decode('utf8')
    data=json.loads(content)
    if not isinstance(data,dict):raise ValueError('Complete manifest object required')
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
    for path in paths:parse(path.read_bytes())
    if a.before and set(a.before)!={'0'}:
        changed=subprocess.check_output(['git','diff','--name-only',a.before,a.after,'--','config'],text=True).splitlines()
        for name in changed:
            if not name.endswith('_review_manifest.json'):continue
            old=subprocess.run(['git','show',a.before+':'+name],capture_output=True)
            if not Path(name).exists():raise ValueError('Manifest removed: '+name)
            if old.returncode==0:validate_update(old.stdout,Path(name).read_bytes())
    print(json.dumps({'status':'passed','complete_manifests_validated':len(paths)}))

if __name__=='__main__':main()

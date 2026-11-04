"""Prepare and verify immutable source jobs. The lease owner applies gate evidence."""
from __future__ import annotations
import argparse, copy, hashlib, json
from pathlib import Path
from datetime import datetime, timezone, timedelta
from tools.content_review.source_worker import digest, file_digest, records, MANIFESTS, WORKFLOW, BRANCH
from tools.content_review.lifecycle import ensure_eligible, instant

def prepare(root,selections,started_at,lease_owner,source_requests_used=0):
    root=Path(root);start=instant(started_at);now=datetime.now(timezone.utc)
    if not start or start>now or now>=start+timedelta(seconds=600):raise ValueError('No work time remains; preserve completion reserve')
    if not 1<=len(selections)<=5 or not 0<=source_requests_used<30:raise ValueError('Initial pilot budgets exceeded')
    result={'schema_version':1,'started_at':start.isoformat(),'work_deadline':(start+timedelta(seconds=600)).isoformat(),'lease_owner':lease_owner,'source_request_limit':30-source_requests_used,'records':[]}
    for collection,cid in selections:
        ensure_eligible(root,collection,cid);p=root/MANIFESTS[collection]
        row=next(r for r in records(json.loads(p.read_text())) if r['candidate_id']==cid)
        ev=row.get('source_processing',{})
        if ev.get('content_sha256')==row['content_sha256'] and ev.get('retrieval_status')=='retrieved':raise ValueError('Consume retained source evidence instead of downloading again')
        result['records'].append({'collection':collection,'candidate_id':cid,'content_sha256':row['content_sha256'],'manifest_sha256':file_digest(p),'url':row['source_url']})
    result['request_id']=digest(result);return result

def verify(request,result,run):
    if result.get('request_id')!=request['request_id']:raise ValueError('Source request mismatch')
    if run.get('event')!='push' or run.get('head_branch')!=BRANCH or run.get('path')!=WORKFLOW or run.get('status')!='completed' or run.get('conclusion')!='success':raise ValueError('Source run not independently verified successful')
    proof=result.get('provenance',{})
    for k,value in [('GITHUB_SHA',run['head_sha']),('GITHUB_RUN_ID',str(run['id'])),('GITHUB_RUN_ATTEMPT',str(run.get('run_attempt',1))),('GITHUB_REF','refs/heads/'+BRANCH),('GITHUB_WORKFLOW_REF','RISEInfoSec/Alex/'+WORKFLOW+'@refs/heads/'+BRANCH)]:
        if proof.get(k)!=value:raise ValueError('Source run provenance mismatch: '+k)
    expected={(r['collection'],r['candidate_id'],r['content_sha256']) for r in request['records']}
    actual=[(r['collection'],r['candidate_id'],r['content_sha256']) for r in result['records']]
    if len(actual)!=len(set(actual)) or set(actual)!=expected:raise ValueError('Source candidate set mismatch')
    if result.get('requests')!=len(result.get('request_log',[])) or not 0<=result['requests']<=request['source_request_limit']:raise ValueError('Source request accounting mismatch')
    for row in result['records']:
        for e in row.get('evidence',[]):
            if hashlib.sha256(e['text'].encode()).hexdigest()!=e['text_sha256']:raise ValueError('Altered source text')
            if not e.get('body_sha256') or not e.get('retrieved_at') or e.get('http_status')!=200:raise ValueError('Missing source byte provenance')
    return True

def retain(manifest,result,receipt_path):
    out=copy.deepcopy(manifest);rows={r['candidate_id']:r for r in records(out)}
    for item in result:
        row=rows[item['candidate_id']]
        if row['content_sha256']!=item['content_sha256']:raise ValueError('Current candidate changed; source result cannot be applied')
        row.setdefault('source_processing_history',[]).append(copy.deepcopy(row.get('source_processing',{})))
        row['source_processing']={'content_sha256':row['content_sha256'],'retrieval_status':item['status'],'receipt':receipt_path,'reason':item.get('reason'),'next_action':item['next_action'],'evidence_sha256':[e['body_sha256'] for e in item.get('evidence',[])]}
        # Deliberately no gate, reviewed hash, recommendation or readiness mutation.
    return out

def main():
    p=argparse.ArgumentParser();p.add_argument('--candidate',action='append',required=True);p.add_argument('--started-at',required=True);p.add_argument('--lease-owner',required=True);p.add_argument('--source-requests-used',type=int,default=0);p.add_argument('--output-dir',type=Path,required=True);a=p.parse_args()
    req=prepare('.', [c.split('/',1) for c in a.candidate],a.started_at,a.lease_owner,a.source_requests_used);a.output_dir.mkdir(parents=True,exist_ok=True);path=a.output_dir/(req['request_id']+'.json');path.write_text(json.dumps(req,ensure_ascii=False,indent=2)+'\n');print(path)
if __name__=='__main__':main()

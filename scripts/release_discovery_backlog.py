"""Release an explicitly authorized, evidence-bound backlog, holding failures per item."""
from __future__ import annotations
import contextlib,csv,hashlib,io,json,os,signal,sys,tempfile,time
from datetime import datetime,timezone
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit
import requests
from jsonschema import Draft202012Validator
from alex.editorial_exclusions import record_keys,load_keys
from alex.pipelines import classify,publish
from alex.pipelines.content_review_release import digest

GATES=('format','access','metadata','duplicates','quality','schema')
HASH_FIELDS=('title','authors','year','doi','source_url','abstract','document_type')

def require(ok,message):
    if not ok:raise ValueError(message)

def check_record(row,weights):
    h=row['content_sha256'];t=row['target']
    require(row['document_type']=='research_paper','Unsupported resource type')
    require(digest({k:row['document_type'] if k=='document_type' else t.get(k,'') for k in HASH_FIELDS})==h,'Reviewed content changed')
    pf=row['preflight'];require(pf['status']=='passed' and pf['content_sha256']==h,'Preflight held or stale')
    for name in GATES:
        c=pf['checks'][name]
        require(c['status']=='passed' and c['content_sha256']==h and c.get('checked_at') and c.get('evidence'),'Missing/stale gate '+name)
    tax=row['taxonomy'];require(tax['status']=='passed' and tax['content_sha256']==h,'Taxonomy held')
    tags=tax['evidence']['classification'];Draft202012Validator(classify.CLASSIFICATION_SCHEMA).validate(tags)
    require(t['Category']==tags['Category'] and t['Investigation_Type']==tags['Investigation_Type'] and t['OSINT_Source_Types']=='; '.join(tags['OSINT_Source_Types']),'Target taxonomy changed')
    a=row['authorization'];q=pf['checks']['quality']['evidence']
    require(q['quality_core_term_gate']=='pass' and q['quality_relevance_gate']=='pass','Quality hard gate')
    if a['route']=='human_approved':
        require(a['decision']=='approved' and a['submission'].get('payload_hash') and a['submission'].get('id'),'Missing completed approval')
        require(float(q['quality_score'])>=float(q['quality_review_threshold']),'Below existing review threshold')
    elif a['route']=='existing_regular_automatic_acceptance':
        require(a['manual_vote_required'] is False and len(a['request_id'])==64,'Invalid automatic handoff')
        threshold=float(weights['preprint_auto_include_threshold'])
        require(float(q['quality_auto_threshold'])==threshold and float(q['quality_score'])>=threshold,'Below existing automatic threshold')
        require('arxiv.org/' in t['source_url'],'Unsupported automatic route')
    else:raise ValueError('Unknown authorization route')
    require(float(t['total_quality_score'])==float(q['quality_score']),'Target score changed')
    require(row['target_schema']['status']=='passed' and row['target_schema']['content_sha256']==h,'Missing target proof')

def check_target(row):
    t=dict(row['target']);h=row['content_sha256'];tags=row['taxonomy']['evidence']['classification']
    # Match the previously verified one-row export. Release-only provenance and
    # collection date do not belong to that historical target digest.
    value={k:t.get(k,'') for k in ('title','authors','year','doi','source_url','abstract','venue','collection_source','collection_url')}
    value['retrieved_at']=row['schema_retrieved_at'];value.update(tags)
    value['OSINT_Source_Types']='; '.join(tags['OSINT_Source_Types']);value['citation_count']=t.get('citation_count')
    value['total_quality_score']=t['total_quality_score'];value['Seminal_Flag']=t['Seminal_Flag']
    with tempfile.TemporaryDirectory() as temp:
        root=Path(temp);(root/'data').mkdir()
        with (root/'data/accepted_classified.csv').open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=list(value));w.writeheader();w.writerow(value)
        with patch.object(publish,'root_file',lambda *parts:root.joinpath(*parts)),patch.object(publish,'generate',lambda *args:None),contextlib.redirect_stdout(io.StringIO()):publish.run()
        result=json.loads((root/'data/papers.json').read_text())
    require(len(result)==1 and digest(result[0])==row['target_schema']['evidence']['target_record_sha256'],'Current publisher target differs')
    json.dumps(result,allow_nan=False)

@contextlib.contextmanager
def deadline():
    def expired(*args):raise TimeoutError('Source request exceeded 20 seconds')
    old=signal.signal(signal.SIGALRM,expired);signal.alarm(20)
    try:yield
    finally:signal.alarm(0);signal.signal(signal.SIGALRM,old)

def source_check(row,get,origins):
    src=row['source_revalidation'];url=src['url'];u=urlsplit(url)
    require(u.scheme=='https' and u.hostname and not u.username and not u.password,'Invalid source URL')
    time.sleep(max(0,2-(time.monotonic()-origins.get(u.netloc,0))))
    try:
        with deadline():r=get(url,timeout=20,allow_redirects=False,headers={'User-Agent':'ALEX-ContentReview/1.0 (+https://github.com/RISEInfoSec/Alex)'})
    finally:origins[u.netloc]=time.monotonic()
    r.raise_for_status();body=r.content
    require(r.status_code==200 and body.startswith(b'%PDF') and hashlib.sha256(body).hexdigest()==src['expected_sha256'],'Approved PDF unavailable or changed')
    return {'source_url':url,'http_status':r.status_code,'pdf_sha256':src['expected_sha256'],'bytes':len(body),'checked_at':datetime.now(timezone.utc).isoformat()}

def release(manifest,corpus,receipt,exclusions,weights,get=requests.get,write=False):
    data=json.loads(Path(manifest).read_text());rows=data['records'];receipt=Path(receipt);corpus=Path(corpus)
    require(data.get('publication_approved') is True and data.get('approval_basis') and digest(rows)==data['records_sha256'],'Authorization/digest mismatch')
    require(len({r['candidate_id'] for r in rows})==len(rows),'Duplicate request identity')
    for r in rows:check_record(r,weights);check_target(r)
    csv.field_size_limit(100000000)
    with corpus.open(newline='') as f:reader=csv.DictReader(f);fields=list(reader.fieldnames);existing=list(reader)
    if receipt.exists():
        prior=json.loads(receipt.read_text());require(prior['records_sha256']==data['records_sha256'],'Receipt changed')
        present={r.get('review_candidate_id'):r for r in existing}
        for r in prior['released']:require(r['candidate_id'] in present and present[r['candidate_id']].get('review_content_sha256')==r['content_sha256'],'Released row missing or changed')
        return {**prior,'already_applied':True}
    keys=set().union(*(record_keys(r) for r in existing));excluded=load_keys(Path(exclusions));origins={};added=[];held=[]
    for r in rows:
        try:
            k=record_keys(r['target']);require(not k&excluded,'Explicit human exclusion');require(not k&keys,'Current corpus/release duplicate')
            proof=source_check(r,get,origins)
        except (ValueError,requests.RequestException,TimeoutError) as exc:
            status=getattr(getattr(exc,'response',None),'status_code',None)
            held.append({'candidate_id':r['candidate_id'],'content_sha256':r['content_sha256'],'title':r['target']['title'],'source_url':r['source_revalidation']['url'],'reason':str(exc),'http_status':status,'approval_preserved':True})
            print('HELD',r['candidate_id'],type(exc).__name__,status,flush=True);continue
        keys.update(k);added.append({**r,'fresh_source_proof':proof});print('VALIDATED',r['candidate_id'],flush=True)
    result={'release_id':data['release_id'],'records_sha256':data['records_sha256'],'approval_basis':data['approval_basis'],'source_review_commit':data['source_review_commit'],'records_before':len(existing),'records_added':len(added),'records_after':len(existing)+len(added),'existing_records_modified':0,'checked_at':datetime.now(timezone.utc).isoformat(),'released':[{k:r[k] for k in ('candidate_id','content_sha256','authorization','fresh_source_proof')} for r in added],'held':held}
    if write:
        fields=list(dict.fromkeys(fields+[k for r in added for k in r['target']]))
        temp=corpus.with_suffix('.release.tmp')
        with temp.open('w',newline='') as f:
            w=csv.DictWriter(f,fieldnames=fields);w.writeheader();w.writerows(existing+[r['target'] for r in added])
        temp.replace(corpus);receipt.parent.mkdir(parents=True,exist_ok=True);receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result

if __name__=='__main__':
    result=release('config/content_review_releases/2026-11-01-discovery-backlog.json','data/accepted_classified.csv','data/content_review_release_receipts/2026-11-01-discovery-backlog.json','config/corpus_exclusions.json',json.loads(Path('config/quality_weights.json').read_text()),write=True)
    print(json.dumps(result,ensure_ascii=False,indent=2))

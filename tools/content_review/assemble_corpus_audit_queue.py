import json,hashlib,collections,sys
from pathlib import Path
root=Path(sys.argv[1])
papers=json.load(open(sys.argv[2]));data=json.load(open(sys.argv[3]))
def h(v):return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
assert data['status']=='complete' and len(data['records'])==len(papers)==3644
byid={r['id']:r for r in papers};assert set(byid)=={r['id'] for r in data['records']}
for r in data['records']:assert r['source_sha256']==h(byid[r['id']])
verification=json.load(open(sys.argv[4]));assert verification['status']=='complete'
verified={r['id']:r for r in verification['records']};assert len(verified)==verification['expected_records']
final=[]
for r in data['records']:
 if r['id'] in verified:
  a=verified[r['id']];assert a['source_sha256']==r['source_sha256'];final.append({**a,'first_pass':r})
 else:
  assert r.get('original_status',r['status'])=='relevant';final.append({**r,'status':'relevant'})
for r in final:
 if byid[r['id']]['summary'].lower().startswith('this paper appears to'):
  r['status']='insufficient_evidence'
  if not r['reason'].startswith('Stored summary uses') and not r['reason'].startswith('Stored summary begins'):
   r['reason']='Stored summary begins with speculative title-derived wording (\"This paper appears to\"); verify the authentic abstract before judging relevance. '+r['reason']
flags=[r for r in final if r['status']!='relevant']
flags.sort(key=lambda r:({'out_of_scope':0,'borderline':1,'insufficient_evidence':2}[r['status']],r['id']))
rows=[]
for i,a in enumerate(flags,1):
 p=byid[a['id']]; identity=p.get('doi') or p.get('source_url') or p['title']
 r=dict(candidate_id='corpus-'+hashlib.sha256(identity.casefold().encode()).hexdigest()[:24],review_number=i,review_batch=(i-1)//20+1,title=p['title'],authors=p.get('author',''),year=p.get('year',''),doi=p.get('doi',''),source_url=p.get('source_url') or p.get('link',''),abstract=p.get('summary',''),document_type='published_corpus_entry',decision='pending',already_published=True,publication_approved=False,review_ready=False,review_purpose='published_corpus_relevance_audit',recommendation='exclude' if a['status']=='out_of_scope' else 'discuss',relevance=a['status'],review_reason=a['reason']+' Evidence: “'+a['evidence_quote']+'”',metadata_issue='Published category: '+str(p.get('category'))+'; investigation type: '+str(p.get('investigation_type'))+'. Audit status: '+a['status']+'. Complete stored abstract screened; full paper and original resource type not reassessed.',original_public_id=p['id'],original_record_sha256=h(p),audit_evidence=a)
 r['content_sha256']=h({k:r.get(k,'') for k in ('title','authors','year','doi','source_url','abstract','document_type')});rows.append(r)
assert len({r['candidate_id'] for r in rows})==len(rows)
assert all(any(r['doi']==doi for r in rows) for doi in ['10.5281/zenodo.19734092','10.5281/zenodo.19734836','10.5281/zenodo.19734635','10.5281/zenodo.19734388','10.5281/zenodo.19735048'])
summary=dict(corpus_records=len(papers),audit_records=len(data['records']),flagged_records=len(rows),batches=(len(rows)+19)//20,status_counts=dict(collections.Counter(r['status'] for r in final)),flagged_by_existing_category=dict(collections.Counter(byid[r['id']]['category'] for r in flags)),usage={'first_pass_reported_lower_bound':data['usage'],'verification':verification['usage'],'limitation':data.get('usage_limitation')},requests=data['requests']+verification['requests'],verification_records=len(verification['records']),corpus_sha256=data['corpus_sha256'],models=sorted({r['model'] for r in final}),audit_workflow_run=40671199156,verification_workflow_run=40672964162,speculative_summary_records=sum(p['summary'].lower().startswith('this paper appears to') for p in papers),excerpt_alignment_count=verification.get('source_excerpt_alignment_count',0),assessment_scope='Complete stored titles and abstracts across all published categories; no full-paper critique, deletion or classification rewrite.')
manifest=dict(schema_version=1,collection='corpus-audit',review_purpose='published_corpus_relevance_audit',summary=summary,records=rows)
(root/'config/corpus_relevance_audit_manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
(root/'config/corpus_relevance_audit_summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(summary,indent=2))
print('Manifest bytes',len((root/'config/corpus_relevance_audit_manifest.json').read_bytes()))

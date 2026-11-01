"""Export bounded current-state audit slices without source abstracts or private review data."""
import csv,gzip,hashlib,io,json,subprocess
from pathlib import Path
from datetime import datetime,timezone

csv.field_size_limit(100000000)
OUT=Path('audit/discovery-20261101');OUT.mkdir(parents=True,exist_ok=True)
DROP={'abstract','summary','affiliations','authors','review_evidence','recommendation_snapshot'}
FIELDS={'id','candidate_id','title','doi','source_url','link','year','discovery_source','discovery_query','total_quality_score','quality_score','relevance_score','venue_score','citation_score','institution_score','institution_bonus','title_anchor_bonus','is_preprint','recommended_action','review_reason','rejection_reason','reject_reason','reason','status','quality_status','quality_core_term_gate','quality_relevance_gate','core_term_gate','relevance_gate','has_abstract','abstract_present','rescore_run_id','scored_at','retrieved_at','Category','Investigation_Type','OSINT_Source_Types','review_candidate_id','review_content_sha256','venue','publisher'}
summary={'checked_at':datetime.now(timezone.utc).isoformat(),'main_commit':subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),'pipeline_state_commit':subprocess.check_output(['git','rev-parse','origin/pipeline-state'],text=True).strip(),'files':{}}

def save(name,rows,source_sha):
    chunks=[];count=0;part=[];headers=set()
    for row in rows:
        headers.update(row)
        r={k:v for k,v in row.items() if k in FIELDS}
        abstract=row.get('abstract') or row.get('summary') or ''
        r['abstract_length']=len(abstract.strip());r['abstract_sha256']=hashlib.sha256(abstract.encode()).hexdigest() if abstract else ''
        part.append(r);count+=1
        if len(part)>=500:
            path=OUT/(name+'-'+str(len(chunks)).zfill(4)+'.json');path.write_text(json.dumps(part,ensure_ascii=False,indent=2)+'\n');chunks.append(path.name);part=[]
    if part:
        path=OUT/(name+'-'+str(len(chunks)).zfill(4)+'.json');path.write_text(json.dumps(part,ensure_ascii=False,indent=2)+'\n');chunks.append(path.name)
    summary['files'][name]={'rows':count,'chunks':chunks,'source_blob':source_sha,'columns':sorted(headers)}
    print('SNAPSHOT',name,count,flush=True)

for name in ('discovery_candidates','accepted_candidates','rejected_candidates','quality_metrics','rescore_metrics'):
    ref='origin/pipeline-state:'+name+'.csv.gz'
    data=subprocess.check_output(['git','show',ref])
    save(name,csv.DictReader(io.TextIOWrapper(gzip.GzipFile(fileobj=io.BytesIO(data)),encoding='utf-8')),subprocess.check_output(['git','rev-parse',ref],text=True).strip())
for name in ('accepted_classified','accepted_harvested','review_queue'):
    path=Path('data')/(name+'.csv')
    with path.open() as f:save(name,csv.DictReader(f),subprocess.check_output(['git','hash-object',str(path)],text=True).strip())
public=json.loads(Path('data/papers.json').read_text())
save('public',public,subprocess.check_output(['git','hash-object','data/papers.json'],text=True).strip())
(OUT/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary,indent=2))

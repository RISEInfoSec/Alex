import csv,hashlib,json
import pandas as pd
import pytest
from alex.editorial_exclusions import record_keys,load_keys,filter_frame
from alex.pipelines.apply_completed_reviews import apply,public_digest
from alex.pipelines.content_review_release import digest,GATES

def save(path,data):
 path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(data))
 return hashlib.sha256(path.read_bytes()).hexdigest()

@pytest.fixture
def release(tmp_path):
 root=tmp_path;old=[dict(id=1,title='GELSI Review',author='Old et al.',year=2024,summary='Speculative'),dict(id=2,title='Keep me',author='Author',year=2023,summary='Real'),dict(id=3,title='GELSI Review',author='Full Author',year=2023,summary='Authentic')]
 save(root/'data/papers.json',old)
 rows=[dict(title=p['title'],authors=p['author'],year=p['year'],abstract=p['summary'],doi='',source_url='') for p in old]
 with (root/'data/accepted_classified.csv').open('w',newline='') as f:
  w=csv.DictWriter(f,fieldnames=rows[0]);w.writeheader();w.writerows(rows)
 def decision(p,value):return dict(candidate_id=str(p['id']),decision=value,title=p['title'],year=p['year'],doi='',source_url='',submission_id='submission',payload_hash='payload',reviewed_content_sha256='reviewhash',original_public_id=p['id'],public_record_sha256=public_digest(p))
 removes=[decision(old[0],'rejected')];keeps=[decision(old[1],'approved')]
 exhash=save(root/'config/corpus_exclusions.json',{'schema_version':1,'records':removes})
 target=dict(title='Approved new paper',authors='Author',year=2026,abstract='Approved abstract',doi='10.1234/new',source_url='https://example.org/new',review_candidate_id='new')
 h=digest({k:'research_paper' if k=='document_type' else target.get(k,'') for k in ('title','authors','year','doi','source_url','abstract','document_type')});target['review_content_sha256']=h
 new=dict(candidate_id='new',collection='weekly',content_sha256=h,document_type='research_paper',decision='approved',submission={'payload_hash':'approval'},target=target,checks={k:dict(status='passed',content_sha256=h,checked_at='now',evidence_sha256='evidence') for k in GATES})
 adds={'release_id':'test-additions','publication_approved':True,'approval_basis':'Explicit approval','source_review_commit':'test','assessment_sha256':'test','expected_records':1,'records':[new],'records_sha256':digest([new])}
 ahash=save(root/'config/additions.json',adds)
 b=dict(release_id='test-reviews',publication_approved=True,approval_basis='Explicit instruction',source_corpus_sha256=hashlib.sha256((root/'data/papers.json').read_bytes()).hexdigest(),source_corpus_records=3,removals=removes,keeps=keeps,records_sha256=digest({'removals':removes,'keeps':keeps}),addition_manifest='config/additions.json',addition_manifest_sha256=ahash,exclusions_sha256=exhash,expected_after=3)
 m=root/'config/reviews.json';save(m,b);return root,m,b

def test_apply_preserves_authentic_version_and_replays(release):
 root,m,b=release;before=(root/'data/accepted_classified.csv').read_bytes()
 assert apply(root,m)['removed']==1 and (root/'data/accepted_classified.csv').read_bytes()==before
 assert apply(root,m,True)['records_after']==3
 rows=list(csv.DictReader((root/'data/accepted_classified.csv').open()))
 assert [r['title'] for r in rows]==['Keep me','GELSI Review','Approved new paper']
 assert rows[1]['abstract']=='Authentic'
 after=(root/'data/accepted_classified.csv').read_bytes();assert apply(root,m,True)['already_applied'];assert (root/'data/accepted_classified.csv').read_bytes()==after

@pytest.mark.parametrize('defect',['authorization','content','dependency','changed_public','conflict'])
def test_fail_closed_before_write(release,defect):
 root,m,b=release
 if defect=='authorization':b['publication_approved']=False
 elif defect=='content':b['removals'][0]['title']='Changed title'
 elif defect=='dependency':b['exclusions_sha256']='wrong'
 elif defect=='changed_public':(root/'data/papers.json').write_text('[]')
 elif defect=='conflict':b['keeps'].append({**b['removals'][0],'decision':'approved'});b['records_sha256']=digest({'removals':b['removals'],'keeps':b['keeps']})
 save(m,b);before=(root/'data/accepted_classified.csv').read_bytes()
 with pytest.raises(ValueError):apply(root,m,True)
 assert (root/'data/accepted_classified.csv').read_bytes()==before

def test_exclusion_variants_and_year_disambiguation(release):
 root,_,_=release;keys=load_keys(root/'config/corpus_exclusions.json')
 assert record_keys({'title':'GELSI—Review','year':'2024.0'})&keys
 assert not record_keys({'title':'GELSI Review','year':2023})&keys
 data=pd.DataFrame([{'title':'GELSI Review','year':2024},{'title':'GELSI Review','year':2023}]);assert filter_frame(data,root/'config/corpus_exclusions.json')['year'].tolist()==[2023]
 assert record_keys({'doi':'https://doi.org/10.1234/ABC'})&record_keys({'doi':'10.1234/abc'})
 assert record_keys({'source_url':'https://EXAMPLE.org/paper/?utm_source=test'})&record_keys({'source_url':'http://example.org/paper'})

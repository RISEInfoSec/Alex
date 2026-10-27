"""Replay reviewed SOUPS abstracts from an explicitly cached official inventory.

Does not fetch, publish, score, approve, or import. Parent must merge against the
current remote state and reconcile completed console decisions before publishing.
"""
import json, hashlib, re
from pathlib import Path
from difflib import SequenceMatcher
from urllib.parse import urlsplit, urlunsplit

ROOT=Path(__file__).resolve().parents[1]
def norm(v): return re.sub(r'\s+',' ',re.sub(r'[^a-z0-9]+',' ',str(v or '').lower())).strip()
def canonical(v):
 p=urlsplit(v or '');return urlunsplit(('https',p.netloc.lower().removeprefix('www.'),p.path.rstrip('/'),p.query,''))
def doi(v): return re.sub(r'^https?://(?:dx\.)?doi.org/','',str(v or '').lower().strip())
def digest(r):return hashlib.sha256(json.dumps({k:r.get(k,'') for k in ('title','authors','year','doi','source_url','abstract','document_type')},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
def build():
 base=json.loads(Path('/tmp/soups-batch10-publish.json').read_text())
 original={r['candidate_id']:r for r in base['records'] if isinstance(r.get('review_number'),int)}
 assert max(r['review_number'] for r in original.values())==198
 selected=json.loads(Path('/tmp/soups-backlog-selected.json').read_text())
 assessments=json.loads((ROOT/'config/soups_backlog_assessments_11_14.json').read_text())
 byid={r['candidate_id']:r for r in base['records']}
 corpus_path=Path('/tmp/alex-current-papers.json');corpus=json.loads(corpus_path.read_text())
 baseline_sha=hashlib.sha256(corpus_path.read_bytes()).hexdigest()
 lookup=[(norm(r.get('title')),doi(r.get('doi')),{canonical(r.get(k)) for k in ('source_url','Harvest_Source_URL','apwg_source_url','link') if r.get(k)},r) for r in corpus]
 evidence=[];new=[]
 for a in assessments['records']:
  r=byid[selected[a['review_number']-199]['candidate_id']]
  assert not r.get('review_number') and r['screening_status']=='not_assessed' and r['abstract']
  cache=ROOT/'.cache/soups'/('year-'+str(r['year'])+'.html')
  assert cache.exists(),str(cache)
  ah=hashlib.sha256(r['abstract'].encode()).hexdigest()
  evidence.append(dict(candidate_id=r['candidate_id'],review_number=a['review_number'],title=r['title'],source_url=r['source_url'],abstract_source=r.get('abstract_source') or r['discovery_url'],abstract_sha256=ah,cached_page=str(cache.relative_to(ROOT)),cached_page_sha256=hashlib.sha256(cache.read_bytes()).hexdigest(),acquisition='existing cached official annual program; not freshly refetched',abstract=r['abstract'],metadata_status=r['metadata_status']))
  matches=[];possible=[];nt=norm(r['title']);nd=doi(r.get('doi'));nu=canonical(r['source_url'])
  for ot,od,urls,old in lookup:
   match={k:old.get(k,'') for k in ('title','year','doi','source_url')}
   if nt==ot or (nd and nd==od) or nu in urls:matches.append(match)
   elif ot:
    m=SequenceMatcher(None,nt,ot)
    if m.real_quick_ratio()>=.9 and m.quick_ratio()>=.9 and m.ratio()>=.9:possible.append(match)
  r.update(review_number=a['review_number'],review_batch=7+(a['review_number']-119)//20,recommendation=a['recommendation'],relevance=a['relevance'],review_reason=a['review_reason'],assessment_date=assessments['assessment_date'],assessment_basis=assessments['assessment_basis'],review_evidence=[r.get('abstract_source') or r['discovery_url'],r['source_url']],screening_status='abstract_review_complete',abstract_text_status='cached_official_program_abstract_substantively_read',metadata_issue=a['limitation']+' Evidence is the cached official program abstract; individual bibliography, full paper, DOI and citation lookup, quality scoring and import checks remain pending.',full_paper_reviewed=False,publication_approved=False,decision='pending',quality_status='not_run',classification_status='not_proposed',citation_count=None,citation_status='not_looked_up',source_abstract_sha256=ah)
  r['duplicate_check']=dict(status='existing_match' if matches else 'possible_variant_hold' if possible else 'no_match_found',matches=matches or possible,doi_check='performed' if nd else 'pending_missing_doi')
  r['dedupe_evidence']=dict(corpus_sha256=baseline_sha,corpus_records=len(corpus),date='2026-10-27',scope='Normalized title, supplied DOI, canonical URL; fuzzy title threshold0.90; alternate versions remain a limitation')
  r['content_sha256']=digest(r)
  # New user instruction: preflight precedes manual review. These cached
  # abstract assessments are evidence, not mechanically cleared queue entries.
  r['reserved_review_number']=r.pop('review_number')
  r['reserved_review_batch']=r.pop('review_batch')
  r.update(review_ready=False,editorial_queue_eligible=False,preflight_status='pending',readiness_status='preflight_hold',preflight_blockers=['written_paper_format_not_verified','live_source_access_not_revalidated','individual_bibliography_pending','identifier_search_pending','citation_evidence_pending','existing_quality_policy_not_run','final_cross_queue_deduplication_pending'])
  new.append(r)
 assert all(byid[k]==r for k,r in original.items()),'Old records changed'
 assert len({r['candidate_id'] for r in base['records']})==len(base['records'])
 base['reviewed_candidates']=len(original)
 base['substantive_abstract_assessments']+=len(new)
 base['latest_prepared_batch']=dict(reserved_first=199,reserved_last=max(r['reserved_review_number'] for r in new),reserved_batches=sorted({r['reserved_review_batch'] for r in new}),pending=0,substantively_assessed=len(new),preflight_held=len(new),assessment_basis=assessments['assessment_basis'])
 Path('/tmp/soups-backlog-ready.json').write_text(json.dumps(base,ensure_ascii=False,indent=2)+'\n')
 Path('/tmp/soups-backlog-held.json').write_text(json.dumps(base,ensure_ascii=False,indent=2)+'\n')
 (ROOT/'config/soups_backlog_cached_evidence_11_14.json').write_text(json.dumps({'records':evidence},ensure_ascii=False,indent=2)+'\n')
 Path('/tmp/soups-backlog-new-records.json').write_text(json.dumps(new,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(dict(substantively_assessed=len(new),review_ready=0,preflight_held=len(new),reserved_batches=sorted({r['reserved_review_batch'] for r in new}),old_records_preserved=len(original),duplicate_holds=[r['reserved_review_number'] for r in new if r['duplicate_check']['status']!='no_match_found'])))
if __name__=='__main__':build()

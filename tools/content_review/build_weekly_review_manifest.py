"""Build review-ready weekly candidates from individually authored abstract assessments.
No title-only approval, threshold change, publication or corpus write occurs.
"""
import csv,sys,json,re,hashlib,html,unicodedata,io
from collections import Counter
from pathlib import Path
from difflib import SequenceMatcher
from urllib.parse import urlsplit,urlunsplit
ROOT=Path(__file__).resolve().parents[2]
HERE=Path(__file__).parent
SOURCE=Path('/tmp/alex-weekly-review-queue.csv')
DATE='2026-10-27'
def norm(v):
 s=unicodedata.normalize('NFKD',html.unescape(str(v or '')).lower())
 return ' '.join(re.findall('[a-z0-9]+',s))
def doi(v):return re.sub(r'^https?://(?:dx\.)?doi.org/','',str(v or '').strip().lower())
def url(v):
 p=urlsplit(str(v or ''));return urlunsplit(('https',p.netloc.lower().removeprefix('www.'),p.path.rstrip('/'),p.query,''))
def sha(v):return hashlib.sha256(v).hexdigest()
def number(v):
 try:return float(v)
 except (ValueError,TypeError):return None
def build():
 csv.field_size_limit(sys.maxsize)
 raw=SOURCE.read_bytes();source=list(csv.DictReader(io.StringIO(raw.decode())))
 inputs=json.loads((HERE/'weekly_screening_inputs.json').read_text());index={r['screen_number']:r for r in inputs}
 assessments=list(csv.DictReader((HERE/'weekly_assessments.tsv').open(),delimiter='\t'))
 corpus=json.loads((ROOT/'alex-seo/data/papers.json').read_text())
 for path in [ROOT/'alex-soups/config/soups_review_manifest.json',ROOT/'alex-virusbulletin/data/review_manifest.json']:
  corpus.extend(json.loads(path.read_text()).get('records',[]))
 titles=[(norm(r.get('title')),r) for r in corpus];dois={doi(r.get('doi')) for r in corpus if r.get('doi')}
 urls={url(r.get(k)) for r in corpus for k in ('source_url','Harvest_Source_URL','pdf_url','paper_url') if r.get(k)}
 records=[];holds=[dict(screen_number=n,reason=reason) for n,reason in [(41,'abstract_not_substantive'),(44,'truncated_abstract'),(78,'duplicate_of_screen_77_html_entity_variant'),(84,'software_release_requires_resource_adapter'),(117,'truncated_abstract'),(119,'podcast_requires_audio_resource_adapter'),(143,'book_description_requires_substantive_text_review')]];seen=set();seen_titles=set();weights=json.loads((ROOT/'alex-seo/config/quality_weights.json').read_text())
 for a in assessments:
  r=index[int(a['screen_number'])]; title=norm(r['title']);identity=doi(r['doi']) or url(r['source_url']) or title
  if r['screen_number']==143:continue
  original=source[r['source_row']]
  if any(original.get(k)!=v for k,v in r.items() if k not in ('screen_number','source_row')):raise ValueError('Source row changed since assessment: '+str(r['screen_number']))
  if identity in seen or title in seen_titles:holds.append(dict(screen_number=r['screen_number'],reason='within_queue_duplicate'));continue
  matches=[]
  for t,old in titles:
   if title==t or (doi(r['doi']) and doi(r['doi'])==doi(old.get('doi'))):matches.append(old.get('title'));continue
   m=SequenceMatcher(None,title,t)
   if m.real_quick_ratio()>=.9 and m.quick_ratio()>=.9 and m.ratio()>=.9:matches.append(old.get('title'))
  if matches or url(r['source_url']) in urls:
   holds.append(dict(screen_number=r['screen_number'],reason='duplicate_or_possible_variant',matches=matches));continue
  abstract=r['abstract'].strip()
  if not abstract or len(abstract)<400 or len(abstract)>6500:raise ValueError('Invalid assessed evidence')
  seen.add(identity);seen_titles.add(title)
  if len(records)>=138:holds.append(dict(screen_number=r['screen_number'],reason='assessed_reserve_outside_initial_138'));continue
  n=len(records)+1;year=int(float(r['year']));preprint=r['is_preprint'].lower()=='true'
  recent=2026-year<weights['recent_paper_window_years'];auto=weights['preprint_auto_include_threshold'] if preprint or recent else weights['auto_include_threshold'];review=weights['preprint_review_threshold'] if preprint or recent else weights['review_threshold']
  score=number(r['total_quality_score'])
  if score is None:quality_status='quality_score_missing_hold'
  elif score<review:quality_status='below_existing_review_threshold_hold'
  else:quality_status='existing_human_quality_review_required'
  dtype={83:'book_chapter',136:'book_chapter',145:'research_report'}.get(r['screen_number'],'research_paper_candidate')
  row=dict(candidate_id='weekly-'+sha(identity.encode())[:24],upstream_candidate_id=r['candidate_id'],upstream_stable_identity=identity,source_row=r['source_row'],review_number=n,review_batch=(n-1)//20+1,batch=(n-1)//20+1,
   title=r['title'],authors=r['authors'],year=year,doi=doi(r['doi']),source_url=r['source_url'],document_type=dtype,document_type_basis='Explicit chapter description in cached abstract; original document remains unverified.' if dtype=='book_chapter' else ('Survey research report metadata and abstract; original document remains unverified.' if dtype=='research_report' else 'Unconfirmed scholarly-discovery record; DOI or PDF does not verify paper format. Original publication type verification required.'),format_verification_status='hold_original_document_type_unverified',abstract=abstract,
   abstract_source=r['source_url'],assessment_basis='Substantive reading of complete cached abstract carried by the weekly scholarly discovery record; not a fresh publisher-page or full-paper assessment.',review_evidence=[r['source_url'],'https://raw.githubusercontent.com/RISEInfoSec/Alex/main/data/review_queue.csv'],
   collection_id='weekly',collection_source='ALEX regular weekly discovery review queue',collection_url='https://github.com/RISEInfoSec/Alex',
   recommendation=a['recommendation'],relevance=a['relevance'],review_reason=a['review_reason'],metadata_issue=a['limitation']+' Cached scholarly-discovery abstract assessed. Original publisher format, metadata, DOI/citation provenance and full text require verification. Existing quality review remains; selection does not clear quality holds. '+f'Upstream quality score: {score:g}; effective review threshold: {review:g}; effective automatic-inclusion threshold: {auto:g}; quality status: {quality_status}.',
   screening_status='cached_abstract_review_complete',assessment_depth='cached_abstract',assessment_date=DATE,full_paper_reviewed=False,paper_format_verified=False,source_verification_status='cached_discovery_evidence; publisher_retrieval_pending',quality_status=quality_status,resource_usefulness_policy='Across all sources, verified slides/presentations without substantive audio must receive the resource-usefulness deduction and cannot automatically qualify; a matching full recording with usable audio requires verification before removing that deduction.',resource_usefulness_status='document_format_unverified; no_audio_match_verified',manual_review_required=True,
   total_quality_score=score,quality_score=score,quality_auto_threshold=auto,quality_review_threshold=review,relevance_score=number(r['relevance_score']),is_preprint=preprint,venue=r['venue'],
   citation_count=number(r.get('citation_count')),citation_status='upstream_value_not_independently_verified' if r.get('citation_count') else 'unknown',doi_status='upstream_identifier_not_independently_verified' if r['doi'] else 'lookup_pending',
   source_recommended_action=r['recommended_action'],source_review_reason=r['review_reason'],discovery_source=r['discovery_source'],discovery_query=r['discovery_query'],source_scored_at=r['scored_at'],
   decision='pending',publication_approved=False,duplicate_check=dict(status='no_match_found',matches=[],basis='DOI, normalized title and URL, fuzzy title ratio0.90 against local current corpus and curated queues; missing metadata and alternate versions remain limitations'),
   source_record_sha256=sha(json.dumps(original,sort_keys=True,ensure_ascii=False).encode()),assessed_text_sha256=sha(abstract.encode()))
  for key in ('venue_score','citation_score','institution_score','institution_bonus','title_anchor_bonus'):row[key]=number(r.get(key))
  fields=('title','authors','year','doi','source_url','abstract','document_type')
  row['content_sha256']=sha(json.dumps({k:row.get(k,'') for k in fields},sort_keys=True,ensure_ascii=False).encode())
  records.append(row)
 evidence_counts=Counter('empty_abstract' if not r.get('abstract','').strip() else 'abstract_under_400_characters' if len(r['abstract'].strip())<400 else 'abstract_over_6500_characters' if len(r['abstract'].strip())>6500 else 'abstract_400_to_6500_characters' for r in source)
 source_summary=dict(url='https://raw.githubusercontent.com/RISEInfoSec/Alex/main/data/review_queue.csv',source_sha256=sha(raw),raw_records=len(source),nonempty_abstracts=sum(bool(r.get('abstract','').strip()) for r in source),abstract_length_inventory=dict(evidence_counts),discovery_source_counts=dict(Counter(r['discovery_source'] for r in source)),decision_tier_counts=dict(Counter(r['recommended_action'] for r in source)),screened_slice_count=len(inputs),future_arrivals='Retain all 4041 raw records outside active buffer and inspect CSV updates hourly; ingest changed source fingerprints additively and never reset completed decisions.',priority_note='Zenodo and other providers were not rejected globally; this initial slice prioritises complete scholarly abstracts from selected providers. Excluded provider records remain in raw inventory.')
 manifest=dict(schema_version=1,collection_id='weekly',collection_source='ALEX regular weekly discovery review queue',run_date=DATE,publication_approved=False,source_inventory=source_summary,records=records,prepared_count=len(records),assessment_count=len(assessments),duplicate_holds=holds,automatic_acceptance_policy='Preserve existing source-appropriate automatic acceptance. These are explicit existing human-review-tier records; no quality exceptions granted.',backlog_is_not_review_ready=True)
 Path('/tmp/weekly-ready-manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
 (HERE/'weekly_preparation_receipt.json').write_text(json.dumps(dict(source_inventory=source_summary,prepared_count=len(records),assessments=len(assessments),recommendation_counts=dict(Counter(r['recommendation'] for r in records)),document_type_counts=dict(Counter(r['document_type'] for r in records)),filter_reason_counts=dict(Counter(r['reason'] for r in holds)),holds=holds,candidate_ids=[r['candidate_id'] for r in records]),ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(dict(prepared=len(records),assessed=len(assessments),holds=holds,source_sha256=source_summary['source_sha256'])))
if __name__=='__main__':build()


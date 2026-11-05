"""Versioned, manual-only text resource contract; paper scoring is unchanged."""
from __future__ import annotations
import contextlib
import csv
import hashlib
import io
import json
import re
import tempfile
from pathlib import Path
from unittest.mock import patch
from urllib.parse import urlsplit

POLICY = 'manual-text-resources-v1'
TYPES = {'best_practice_guide', 'technical_report', 'investigative_journalism'}
HASH_FIELDS = ('title','authors','year','doi','source_url','abstract','document_type')
COMMON = ('accountability','substantive_material','investigative_relevance','evidence_or_guidance')
SPECIFIC = {'best_practice_guide':('version','actionable_scope'),
            'technical_report':('methods','data_provenance'),
            'investigative_journalism':('sourcing','investigative_method')}

def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()

def require(ok, message):
    if not ok: raise ValueError(message)

def hash64(value):
    return bool(re.fullmatch('[0-9a-f]{64}',str(value or '')))

def validate_assessment(row):
    kind=row.get('document_type'); a=row.get('resource_assessment',{})
    require(kind in TYPES, 'Unsupported manual resource type')
    require(a.get('schema_version')==1 and a.get('policy')==POLICY, 'Unapproved resource policy/schema')
    require(a.get('actual_type')==kind and row.get('verified_document_type',kind)==kind, 'Actual resource type mismatch')
    h=row.get('content_sha256')
    require(hash64(h) and digest({k:row.get(k,'') for k in HASH_FIELDS})==h, 'Reviewed resource content changed')
    require(a.get('content_sha256')==h, 'Stale resource assessment')
    require(a.get('manual_only') is True and a.get('quality_method')=='qualitative', 'Manual qualitative route required')
    require(a.get('summary_kind')=='editorial_synopsis' and row.get('summary_kind')=='editorial_synopsis', 'Synopsis must be identified as editorial')
    for flag in ('automatic_acceptance_eligible','automatic_route_eligible','automatic_handoff_pending'):
        require(row.get(flag) is not True, 'Automatic acceptance is forbidden for non-papers')
    require(row.get('automatic_route',{}).get('eligible') is not True, 'Automatic acceptance is forbidden for non-papers')
    require(not any(a.get(k) is not None for k in ('quality_score','citation_count','bibliometric_score')), 'Numeric paper scores forbidden in resource assessment')
    require(all(str(row.get(k,'')).strip() for k in ('title','authors','venue','abstract','source_url')), 'Verified resource metadata required')
    require(urlsplit(row['source_url']).scheme=='https', 'Canonical HTTPS source required')
    require(a.get('publication_date')==row.get('publication_date') and bool(re.fullmatch(r'\d{4}-\d{2}(?:-\d{2})?',str(a.get('publication_date','')))), 'Original publication date required')
    require(str(row['year'])==str(a['publication_date'])[:4], 'Publication year mismatch')
    require(a.get('assessed_at') and a.get('assessor') and a.get('limitations'), 'Assessment attribution and limitations required')
    require(a.get('text_complete') is True or a.get('assessment_limits'), 'Complete text or explicit assessment limits required')
    require(hash64(a.get('source_sha256')) and hash64(a.get('text_sha256')) and a.get('source_receipt'), 'Retained source evidence required')
    require(str(a.get('publication_version') or '')==str(row.get('publication_version') or ''), 'Publication version mismatch')
    if kind=='best_practice_guide':require(a.get('publication_version'), 'Guide version required')
    for key in (*COMMON,*SPECIFIC[kind]):
        check=a.get('criteria',{}).get(key,{})
        require(check.get('status')=='passed' and check.get('evidence'), 'Missing qualitative criterion: '+key)
    require(row.get('resource_assessment_sha256')==digest(a), 'Resource assessment digest mismatch')
    return a

def validate_taxonomy(row):
    from jsonschema import Draft202012Validator
    from alex.pipelines.classify import CLASSIFICATION_SCHEMA
    a=validate_assessment(row); tax=row.get('taxonomy',{})
    require(tax.get('status')=='passed' and tax.get('content_sha256')==row['content_sha256'], 'Resource taxonomy held or stale')
    evidence=tax.get('evidence',{})
    require(evidence.get('contract')==POLICY and evidence.get('resource_assessment_sha256')==digest(a), 'Resource classifier contract mismatch')
    require(evidence.get('method')=='substantive_resource_assessment' and evidence.get('rationale'), 'Evidence-based resource taxonomy required')
    tags=evidence.get('classification',{})
    Draft202012Validator(CLASSIFICATION_SCHEMA).validate(tags)
    return tags

def corpus_value(row):
    a=validate_assessment(row); tags=validate_taxonomy(row)
    value={k:row.get(k,'') for k in (*HASH_FIELDS,'venue','collection_source','collection_url','retrieved_at','publication_date','publication_version')}
    value.update(tags)
    value.update(OSINT_Source_Types='; '.join(tags['OSINT_Source_Types']),
        citation_count='',total_quality_score='',Seminal_Flag='FALSE',
        resource_schema_version=1,summary_kind='editorial_synopsis',
        resource_assessment=json.dumps(a,ensure_ascii=False,sort_keys=True),
        resource_assessment_sha256=digest(a),review_candidate_id=row['candidate_id'],
        review_content_sha256=row['content_sha256'],inclusion_path=POLICY)
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}',a['publication_date']):
        value.update(publication_date_status='verified',publication_date_source=row['source_url'],
            publication_date_basis='Original publication date of assessed resource, verified in retained publisher metadata')
    return value

def public_fields(row):
    """Only typed resources add fields, keeping existing paper serialization stable."""
    kind=row.get('document_type','')
    if not kind or kind=='research_paper':return {}
    require(kind in TYPES, 'Unsupported public resource type')
    raw=row.get('resource_assessment');a=json.loads(raw) if isinstance(raw,str) else raw
    # The full prepublication contract is enforced by release. Recheck the
    # content/assessment binding on every later corpus export as well.
    value=dict(row);value.update(content_sha256=row.get('review_content_sha256'),resource_assessment=a)
    # CSV has no JSON scalar types. Recover an integer year only when that
    # exact reconstruction matches the immutable reviewed-content digest.
    # Never recompute or replace the accepted digest to make a row pass.
    if digest({k:value.get(k,'') for k in HASH_FIELDS}) != value['content_sha256']:
        year=value.get('year')
        if isinstance(year,str) and re.fullmatch(r'0|[1-9][0-9]*',year):
            value['year']=int(year)
    validate_assessment(value)
    require(row.get('total_quality_score') in ('',None), 'Non-paper cannot carry a paper quality score')
    result=dict(resource_schema_version=1,document_type=kind,summary_kind='editorial_synopsis',
        publication_version=str(row.get('publication_version') or ''),seminal=None,
        quality_tier='Qualitative assessment',resource_assessment_sha256=digest(a),
        quality_assessment={'method':'qualitative','policy':POLICY,
            'limitations':a['limitations'],'assessment_limits':a.get('assessment_limits'),
            'criteria':a['criteria'],'assessed_at':a['assessed_at']})
    if a.get('original_publication_date'):result['original_publication_date']=a['original_publication_date']
    return result

def dry_run(row):
    from alex.pipelines import publish
    value=corpus_value(row)
    with tempfile.TemporaryDirectory(prefix='alex-resource-') as temp:
        root=Path(temp);(root/'data').mkdir()
        with (root/'data/accepted_classified.csv').open('w',newline='') as stream:
            writer=csv.DictWriter(stream,fieldnames=list(value));writer.writeheader();writer.writerow(value)
        with patch.object(publish,'root_file',lambda *p:root.joinpath(*p)),patch.object(publish,'generate',lambda *a:None),contextlib.redirect_stdout(io.StringIO()):publish.run()
        result=json.loads((root/'data/papers.json').read_text())
    require(len(result)==1, 'Resource serialization row count changed')
    result=result[0]
    for left,right in [('title','title'),('authors','author'),('abstract','summary'),('source_url','source_url'),('document_type','document_type')]:
        require(result.get(right)==row[left], 'Resource serialization changed '+left)
    require(result.get('resource_assessment_sha256')==row['resource_assessment_sha256'] and result.get('quality_tier')=='Qualitative assessment' and result.get('seminal') is None, 'Resource assessment export mismatch')
    json.dumps(result,allow_nan=False)
    return result

def validate_release(row):
    """Policy approval is never a candidate decision. No automatic route exists."""
    a=validate_assessment(row);tags=validate_taxonomy(row);h=row['content_sha256']
    auth=row.get('authorization',{})
    require(auth.get('route')=='human_approved' and auth.get('decision')=='approved', 'Content-bound human approval required')
    require(auth.get('content_sha256')==h and auth.get('resource_assessment_sha256')==digest(a), 'Human approval is stale or lacks assessment binding')
    submission=auth.get('submission',{})
    require(submission.get('id') and hash64(submission.get('payload_hash')) and isinstance(submission.get('revision'),int) and submission['revision']>0, 'Completed manual submission required')
    pf=row.get('preflight',{})
    require(pf.get('status')=='passed' and pf.get('content_sha256')==h, 'Resource preflight incomplete')
    for gate in ('format','access','metadata','duplicates','quality','schema'):
        c=pf.get('checks',{}).get(gate,{})
        require(c.get('status')=='passed' and c.get('content_sha256')==h and c.get('checked_at') and c.get('evidence') and not c.get('stale'), 'Resource gate held or stale: '+gate)
    require(pf['checks']['quality']['evidence'].get('resource_assessment_sha256')==digest(a), 'Qualitative gate binding mismatch')
    require(row.get('target')==corpus_value(row), 'Resource target changed')
    proof=row.get('target_schema',{})
    require(proof.get('status')=='passed' and proof.get('content_sha256')==h and proof.get('evidence',{}).get('target_record_sha256')==digest(dry_run(row)), 'Current resource serialization differs')
    source=row.get('source_revalidation',{})
    require(source.get('url')==row['source_url'] and source.get('expected_sha256')==a['source_sha256'] and source.get('kind') in ('exact_pdf','exact_resource_html'), 'Exact assessed source revalidation required')
    return tags

def release_record(row, decision, submission):
    """Bind an observed completed D1 decision; never infer it from policy approval."""
    import copy
    validate_assessment(row)
    context=decision.get('recommendation_snapshot')
    if isinstance(context,str):context=json.loads(context)
    require(isinstance(context,dict) and context.get('resource_assessment_sha256')==row['resource_assessment_sha256'], 'Manual decision did not review this assessment')
    require(decision.get('decision')=='approved' and decision.get('candidate_id')==row['candidate_id'] and decision.get('content_sha256')==row['content_sha256'], 'Current manual candidate decision required')
    require(context.get('content_sha256')==row['content_sha256'], 'Manual decision snapshot changed')
    require(decision.get('submission_id')==submission.get('id') and decision.get('revision')==submission.get('revision') and decision.get('collection')==submission.get('collection') and decision.get('batch')==submission.get('batch') and decision.get('user_id')==submission.get('user_id'), 'Decision/submission mismatch')
    result=copy.deepcopy(row)
    result['authorization']={'route':'human_approved','decision':'approved','content_sha256':row['content_sha256'],
        'resource_assessment_sha256':row['resource_assessment_sha256'],
        'submission':{k:submission.get(k) for k in ('id','revision','payload_hash')}}
    a=row['resource_assessment']
    result['source_revalidation']={'url':row['source_url'],'kind':'exact_pdf' if row['source_url'].lower().endswith('.pdf') else 'exact_resource_html','expected_sha256':a['source_sha256']}
    validate_release(result)
    return result

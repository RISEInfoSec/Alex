"""Prepare verified retained text for manual review, without source/model calls."""
import copy
from alex.resource_types import POLICY, TYPES, HASH_FIELDS, digest, validate_assessment, validate_taxonomy, dry_run, corpus_value
from tools.content_review.typed_resource import validate_staging

def prepare(row, assessment, tags, taxonomy_rationale, synopsis, stamp):
    stage=validate_staging(row)
    if stage['actual_type'] not in TYPES or row.get('decision','pending') not in ('pending','unreviewed'):
        raise ValueError('Only pending supported text resources can be prepared')
    for gate in ('format','access','duplicates'):
        c=row.get('preflight',{}).get('checks',{}).get(gate,{})
        if c.get('status')!='passed' or c.get('content_sha256')!=row['content_sha256'] or not c.get('evidence') or c.get('stale'):
            raise ValueError('Verified retained source and current duplicate clearance required: '+gate)
    if len(synopsis.strip())<200:raise ValueError('Substantive editorial synopsis required')
    old=copy.deepcopy(row)
    row.setdefault('reviewed_content_versions',[]).append({'content_sha256':old['content_sha256'],'record':old,
        'reason':'Owner-approved typed resource schema: verified type/metadata and explicitly editorial synopsis.', 'superseded_at':stamp})
    row.update(document_type=stage['actual_type'],authors=stage['author'],abstract=synopsis,
        summary_kind='editorial_synopsis',publication_date=stage['publication_date'],
        publication_version=stage.get('publication_version'),year=int(stage['publication_date'][:4]),
        abstract_truncated=False,abstract_integrity_status='editorial_synopsis_not_source_abstract',
        manual_vote_required=True,automatic_acceptance_eligible=False,automatic_route_eligible=False,
        automatic_handoff_pending=False,review_ready=False,editorial_queue_eligible=False,
        lifecycle_evidence_revision=POLICY)
    h=digest({k:row.get(k,'') for k in HASH_FIELDS});row['content_sha256']=h
    a=copy.deepcopy(assessment)
    a.update(schema_version=1,policy=POLICY,actual_type=stage['actual_type'],content_sha256=h,
        quality_method='qualitative',manual_only=True,summary_kind='editorial_synopsis',assessed_at=stamp,
        source_receipt=stage['source_receipt'],source_sha256=stage['source_sha256'],text_sha256=stage['text_sha256'],
        text_complete=stage['text_complete'],publication_date=stage['publication_date'],publication_version=stage.get('publication_version'))
    row.update(resource_assessment=a,resource_assessment_sha256=digest(a))
    validate_assessment(row)
    row['taxonomy']={'status':'passed','content_sha256':h,'checked_at':stamp,'evidence':{
        'contract':POLICY,'method':'substantive_resource_assessment','classification':copy.deepcopy(tags),
        'rationale':taxonomy_rationale,'resource_assessment_sha256':digest(a),'provider_requests':0}}
    validate_taxonomy(row)
    checks=row['preflight']['checks']
    for gate in ('format','access','duplicates'):
        checks[gate]=copy.deepcopy(checks[gate]);checks[gate].update(content_sha256=h,
            evidence_rebound_at=stamp,reused_from_content_sha256=old['content_sha256'],
            rebinding_reason='Same source bytes, title and canonical URL; reviewed type/metadata/synopsis versioned. No repeat retrieval.')
    checks['metadata']={'status':'passed','checked_at':stamp,'content_sha256':h,'evidence':{
        'method':'Verified retained original source metadata','source_receipt':stage['source_receipt'],
        'author':row['authors'],'publication_date':row['publication_date'],'publication_version':row['publication_version'],
        'summary_kind':'editorial_synopsis','source_sha256':a['source_sha256']}}
    checks['quality']={'status':'passed','checked_at':stamp,'content_sha256':h,'evidence':{
        'policy':POLICY,'quality_method':'qualitative','resource_assessment_sha256':digest(a),
        'criteria':a['criteria'],'limitations':a['limitations'],'manual_only':True}}
    exported=dry_run(row)
    checks['schema']={'status':'passed','checked_at':stamp,'content_sha256':h,'evidence':{
        'method':'Production publisher on disposable one-record fixture','document_type':row['document_type'],
        'target_record_sha256':digest(exported),'resource_assessment_sha256':digest(a),
        'corpus_modified':False,'publication_approved':False}}
    row.update(target=corpus_value(row),target_schema=copy.deepcopy(checks['schema']),schema_retrieved_at=row.get('retrieved_at',''))
    row['preflight'].update(status='passed',content_sha256=h)
    row.update(preflight_blockers=[],preflight_status='passed')
    return row

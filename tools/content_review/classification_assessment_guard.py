"""Read-only structural check for a native abstract classification proposal.

This does not classify text, prove the assessment was actually performed, pass
the schema gate, or authorize publication. A future writer must authenticate the
native run, bind the taxonomy to immutable repository inputs, and independently
recheck the source evidence and private decisions under a write fence. In
particular, a missing-key or failed-API 'Other' fallback is not an assessment.
"""
import hashlib
import re

from tools.content_review.lifecycle import current_pass
from tools.content_review.manifest_integrity import reviewed_digest
from tools.content_review.classification_taxonomy import POLICY

ASCII_TEXT=re.compile(r'^[\x20-\x7e\t\r\n]+$')
FIELDS={'content_sha256','abstract_sha256','method','category','investigation_type','source_types','rationale'}
TAXONOMY={'categories','investigation_types','source_types'}


def inspect(row, assessment, taxonomy):
    if not isinstance(row,dict) or not isinstance(assessment,dict) or not isinstance(taxonomy,dict):
        raise ValueError('Classification inputs required')
    digest=row.get('content_sha256')
    if (not isinstance(digest,str) or not re.fullmatch(r'[0-9a-f]{64}',digest) or reviewed_digest(row)!=digest or
        row.get('document_type')!='research_paper' or row.get('decision','pending') not in ('pending','unreviewed') or
        row.get('publication_status')=='published_live_verified' or row.get('publication_approved') is True):
        raise ValueError('Candidate changed or is ineligible')
    preflight=row.get('preflight');checks=preflight.get('checks') if isinstance(preflight,dict) else None
    gates=('format','access','metadata','duplicates','quality')
    if (not isinstance(checks,dict) or any(not isinstance(checks.get(g),dict) or
        not isinstance(checks[g].get('evidence'),dict) or not checks[g]['evidence'] or
        not isinstance(checks[g].get('checked_at'),str) or not checks[g]['checked_at'] for g in gates) or
        not all(current_pass(row,g) for g in gates)):
        raise ValueError('Current prior classification gates required')
    schema=checks.get('schema')
    if isinstance(schema,dict) and current_pass(row,'schema'):
        return {'status':'held','reason':'existing_schema_pass_preserved','writes':0}
    if schema is not None:
        return {'status':'held','reason':'existing_schema_evidence_requires_reconciliation','writes':0}
    text=row.get('abstract')
    complete=(row.get('abstract_integrity_status')=='verified_complete' or
              isinstance(row.get('abstract_text_status'),str) and row['abstract_text_status'].startswith('cached_official_program_abstract'))
    if (not isinstance(text,str) or not ASCII_TEXT.fullmatch(text) or len(text.strip())<200 or len(text)>30000 or
        not complete or row.get('abstract_truncated') or '[truncated]' in text):
        return {'status':'held','reason':'complete_reviewed_abstract_required','writes':0}
    if set(taxonomy)!=TAXONOMY or any(not isinstance(taxonomy[k],list) or not 1<=len(taxonomy[k])<=100 or
        any(not isinstance(x,str) or not x or len(x)>100 or not ASCII_TEXT.fullmatch(x) for x in taxonomy[k]) or len(set(taxonomy[k]))!=len(taxonomy[k])
        for k in TAXONOMY):
        raise ValueError('Classification taxonomy invalid')
    if taxonomy!=POLICY:
        raise ValueError('Classification taxonomy differs from ALEX policy')
    if set(assessment)!=FIELDS:
        return {'status':'held','reason':'complete_assessment_required','writes':0}
    abstract_hash=hashlib.sha256(text.strip().encode()).hexdigest()
    source_types=assessment.get('source_types');rationale=assessment.get('rationale')
    if (assessment.get('content_sha256')!=digest or assessment.get('abstract_sha256')!=abstract_hash or
        assessment.get('method')!='native_abstract_assessment' or assessment.get('category') not in taxonomy['categories'] or
        assessment.get('investigation_type') not in taxonomy['investigation_types'] or not isinstance(source_types,list) or
        len(source_types)>len(taxonomy['source_types']) or any(not isinstance(x,str) or x not in taxonomy['source_types'] for x in source_types) or
        len(set(source_types))!=len(source_types) or not isinstance(rationale,str) or not ASCII_TEXT.fullmatch(rationale) or len(rationale.strip())<80 or len(rationale)>3000):
        return {'status':'held','reason':'classification_assessment_invalid','writes':0}
    return {'status':'classification_shape_verified','content_sha256':digest,'abstract_sha256':abstract_hash,
            'semantic_classification_verified':False,'native_assessment_authenticated':False,
            'requires_immutable_taxonomy_and_private_decision_recheck':True,'gate_passed':False,
            'publication_authorized':False,'provider_requests':0,'paid_requests':0,'writes':0}

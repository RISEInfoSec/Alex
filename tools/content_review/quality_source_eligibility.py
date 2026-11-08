"""Identify quality-held candidates needing source evidence, without writes.

This is not a request authorization, gate pass or decision. A caller must
also bind immutable manifests, the lease and the live private decision fence.
"""
import re
from tools.content_review.lifecycle import current_pass
from tools.content_review.manifest_integrity import reviewed_digest


def eligible(row):
    if not isinstance(row,dict):raise ValueError('Candidate is unavailable')
    digest=row.get('content_sha256')
    if (not isinstance(digest,str) or not re.fullmatch(r'[0-9a-f]{64}',digest) or reviewed_digest(row)!=digest or
        row.get('decision','pending') not in ('pending','unreviewed') or row.get('publication_status')=='published_live_verified' or
        row.get('publication_approved') is True):raise ValueError('Candidate changed or has a decision')
    if not isinstance(row.get('preflight'),dict) or not isinstance(row['preflight'].get('checks'),dict):
        raise ValueError('Candidate preflight invalid')
    if not all(current_pass(row,g) for g in ('format','access','metadata','duplicates')):
        return {'eligible':False,'reason':'prior_gates_not_current','gate_passed':False,'writes':0}
    quality=row.get('preflight',{}).get('checks',{}).get('quality')
    if (not isinstance(quality,dict) or quality.get('status')!='held' or quality.get('content_sha256')!=digest or
        not quality.get('checked_at') or quality.get('stale') or not isinstance(quality.get('evidence'),dict) or not quality['evidence']):
        return {'eligible':False,'reason':'current_quality_hold_required','gate_passed':False,'writes':0}
    source=row.get('source_processing')
    if source is not None and not isinstance(source,dict):raise ValueError('Source history invalid')
    if isinstance(source,dict) and source.get('content_sha256')==digest and source.get('retrieval_status') in ('retrieved','held'):
        return {'eligible':False,'reason':'source_evidence_or_hold_already_retained','gate_passed':False,'writes':0}
    return {'eligible':True,'reason':'quality_hold_needs_source_evidence','gate_passed':False,'writes':0}

"""Classify corpus-audit decisions without editing or removing public records.

The D1 overlay and derived outcomes are private and must remain in memory;
never log them or publish them to the repository. Rejected audit items are
removal requests, not permission to delete. Any eventual release must use the
existing publication safeguards and recheck the deployed public record.
"""
import hashlib
import json

from tools.content_review.d1_reconcile import reconcile
from tools.content_review.manifest_integrity import reviewed_digest


def plan(snapshot, confirmed_snapshot, manifests, public_records):
    if not isinstance(manifests,dict) or not isinstance(public_records,list):
        raise ValueError('Complete audit and public inventories are required')
    audit=manifests.get('corpus-audit')
    if not isinstance(audit,dict) or not isinstance(audit.get('records'),list):
        raise ValueError('Corpus audit manifest is unavailable')
    indexed={}
    for row in public_records:
        if not isinstance(row,dict) or row.get('id') is None or row['id'] in indexed:
            raise ValueError('Public record identities are incomplete or duplicated')
        indexed[row['id']]=row
    rows={}
    for row in audit['records']:
        if not isinstance(row,dict) or not isinstance(row.get('candidate_id'),str) or row['candidate_id'] in rows:
            raise ValueError('Audit candidate identities are incomplete or duplicated')
        rows[row['candidate_id']]=row
    checked=reconcile(snapshot,confirmed_snapshot,{k:v.get('records',[]) for k,v in manifests.items()})
    outcomes=[]
    for held in checked['held']:
        if held['collection']=='corpus-audit':
            outcomes.append({'candidate_id':held['candidate_id'],'status':'held','reason':held['reason']})
    for decision in checked['matched_decisions']:
        if decision['collection']!='corpus-audit':continue
        cid=decision['candidate_id'];row=rows[cid];source=indexed.get(row.get('original_public_id'))
        reason=None
        if reviewed_digest(row)!=row.get('content_sha256'):reason='reviewed_content_hash_mismatch'
        elif source is None:reason='original_public_record_missing'
        elif hashlib.sha256(json.dumps(source,sort_keys=True,ensure_ascii=False).encode()).hexdigest()!=row.get('original_record_sha256'):
            reason='original_public_record_changed'
        jobs=[j for j in snapshot['jobs'] if j.get('submission_id')==decision['submission_id']
              and j.get('candidate_id')==cid and j.get('kind')=='corpus_removal_review']
        if decision['decision']=='rejected' and len(jobs)!=1:reason=reason or 'removal_review_job_missing_or_ambiguous'
        if reason:
            outcomes.append({'candidate_id':cid,'status':'held','reason':reason})
        else:
            outcomes.append({'candidate_id':cid,'status':'retain' if decision['decision']=='approved' else 'removal_review_requested',
                             'requires_live_public_recheck':True})
    return {'status':'plan_only','outcomes':outcomes,'counts':checked['counts'],
            'publication_authorized':False,'provider_requests':0,'paid_requests':0,'writes':0,
            'requires_remote_lease_and_snapshot_recheck':True}

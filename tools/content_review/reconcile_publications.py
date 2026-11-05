"""Reconcile an immutable release receipt with verified deployed publication targets.

No source checks, paid calls, editorial decisions or corpus writes are performed.
The caller fetches immutable request/receipt bytes and deployed public JSON.
"""
from __future__ import annotations
import copy
import hashlib
import json

PUBLIC_ONLY_OMISSIONS = {'id', 'inclusion_path', 'review_candidate_id', 'review_content_sha256'}


def reconcile(manifest, request, receipt, public_records, *, checked_at, receipt_ref,
              public_url, public_sha256):
    if request.get('release_id') != receipt.get('release_id') or not request.get('release_id'):
        raise ValueError('Release identity mismatch')
    if not request.get('records_sha256') or request['records_sha256'] != receipt.get('records_sha256'):
        raise ValueError('Release records digest mismatch')
    actual = hashlib.sha256(json.dumps(request['records'], sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()
    if actual != request['records_sha256']:
        raise ValueError('Request content digest mismatch')
    requests = {r['candidate_id']: r for r in request['records']}
    released = {r['candidate_id']: r for r in receipt['released']}
    if len(requests) != len(request['records']) or len(released) != len(receipt['released']):
        raise ValueError('Duplicate release identity')
    result = copy.deepcopy(manifest)
    rows = result.get('records', []) + result.get('preflight_records', [])
    rows_by_id = {r['candidate_id']: r for r in rows}
    changed, verified = [], []
    for cid, proof in released.items():
        row, item = rows_by_id.get(cid), requests.get(cid)
        if row is None:  # A receipt may include another collection.
            continue
        if not item or not row.get('content_sha256') or not (row['content_sha256'] == item.get('content_sha256') == proof.get('content_sha256')):
            raise ValueError('Changed reviewed content: ' + cid)
        if row.get('decision') == 'rejected':
            raise ValueError('Publication conflicts with retained rejection: ' + cid)
        target = item['target']
        from alex.resource_types import TYPES, validate_release, dry_run
        if item.get('document_type') in TYPES:
            # Manual resources retain the bound CSV input as target, whereas
            # paper requests retain public JSON. Verify the original approval
            # and assessment before replaying the real disposable exporter.
            validate_release(item)
            if row.get('resource_assessment_sha256') != item.get('resource_assessment_sha256'):
                raise ValueError('Changed resource assessment: ' + cid)
            target = dry_run(item)
        # The public exporter omits internal provenance and reassigns numeric IDs.
        fields = {k: v for k, v in target.items() if k not in PUBLIC_ONLY_OMISSIONS}
        matches = [p for p in public_records if all(k in p and p[k] == v for k, v in fields.items())]
        if len(matches) != 1:
            raise ValueError('Deployed target missing, changed or duplicated: ' + cid)
        # Match the manifest content as well as the saved digest; never infer a
        # successful release of a different revision from a title alone.
        for key, target_key in (('title','title'), ('authors','author'), ('abstract','summary'), ('source_url','source_url'), ('year','year')):
            if row.get(key) != target.get(target_key):
                raise ValueError('Manifest content differs from release target: ' + cid)
        verified.append(cid)
        automatic = item.get('authorization', {}).get('route') == 'existing_regular_automatic_acceptance'
        consumed = not automatic or (row.get('automatic_handoff_status') == 'consumed_published' and not row.get('automatic_handoff_pending'))
        if row.get('publication_status') == 'published_live_verified' and consumed:
            continue
        row.update(publication_status='published_live_verified', publication_receipt=receipt_ref,
                   published_at=receipt['checked_at'], public_verification={
                       'checked_at':checked_at, 'url':public_url, 'public_records':len(public_records),
                       'public_record_id':matches[0]['id'], 'public_sha256':public_sha256,
                       'method':'Exactly one deployed record equals every public field of the immutable release target; current reviewed hash matches request and successful receipt.'},
                   review_ready=False, editorial_queue_eligible=False, batch_admission_eligible=False,
                   admission_hold=None)
        if item.get('authorization', {}).get('route') == 'existing_regular_automatic_acceptance':
            row.update(automatic_handoff_status='consumed_published', automatic_handoff_pending=False)
            if isinstance(row.get('automatic_route'), dict):
                row['automatic_route'].update(release_status='consumed_published', publication_status='published_live_verified', next_action='Publication verified; no further processing required.')
        changed.append(cid)
    pending = [r for r in rows if r.get('publication_status') != 'published_live_verified' and r.get('decision') not in ('approved','rejected')]
    result['automatic_handoff_pending_count'] = sum(bool(r.get('automatic_handoff_pending')) and r.get('automatic_handoff_status') != 'consumed_published' for r in pending)
    result['mechanical_passed_awaiting_batch_admission'] = sum(bool(r.get('batch_admission_eligible')) and not r.get('review_ready') for r in pending)
    result['batch_admission_eligible_count'] = result['mechanical_passed_awaiting_batch_admission']
    if changed:
        result['last_publication_reconciliation'] = {'checked_at':checked_at, 'receipt':receipt_ref, 'verified_candidates':verified, 'changed_candidates':changed}
    return result, {'changed_candidates':changed, 'verified_candidates':verified, 'automatic_handoff_pending':result['automatic_handoff_pending_count']}

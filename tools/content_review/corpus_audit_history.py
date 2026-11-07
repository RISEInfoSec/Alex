"""Recognize receipt-bound historical audit outcomes without replaying them.

This read-only plan does not claim that today's public corpus has the same
contents, authorize deletion, modify decisions, or perform a provider request.
The caller keeps D1 rows and outcome identities private and rechecks remote
heads before any future leased write or publication.
"""
from collections import Counter
from copy import deepcopy
import hashlib
import json

from tools.content_review.corpus_audit_adapter import plan as current_plan
from tools.content_review.d1_reconcile import reconcile
from tools.content_review.manifest_integrity import reviewed_digest
from tools.content_review.verified_inputs import SHA, _git, _path_blob

RELEASE = '2026-10-28-completed-reviews'
APPLICATION = 'config/review_application_status.json'
SAVED_RECEIPT = 'config/content_review_publication_receipts/' + RELEASE + '.json'
RELEASE_REQUEST = 'config/content_review_releases/' + RELEASE + '.json'
PUBLIC_RECEIPT = 'data/content_review_release_receipts/' + RELEASE + '.json'


def _json(repo, commit, path):
    raw, metadata = _path_blob(repo, commit, path)
    try:
        value = json.loads(raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError('Historical audit evidence is invalid JSON') from exc
    if not isinstance(value, dict):raise ValueError('Historical audit evidence is not an object')
    return value, metadata


def plan(repo, review_head, main_head, snapshot, confirmed_snapshot, manifests, public_records, *, observed_heads):
    if not all(isinstance(x, str) and SHA.fullmatch(x) for x in (review_head, main_head)):
        raise ValueError('Immutable review and main commits are required')
    if not isinstance(observed_heads, dict) or observed_heads.get('review') != review_head or observed_heads.get('main') != main_head:
        raise ValueError('Current review and main heads are unavailable or changed')
    application, application_meta = _json(repo, review_head, APPLICATION)
    saved, saved_meta = _json(repo, review_head, SAVED_RECEIPT)
    public_commit = application.get('public_commit')
    if (application.get('schema_version') != 1 or application.get('release_id') != RELEASE
        or application.get('status') != 'published_live_verified' or application.get('publication_receipt') != SAVED_RECEIPT
        or not isinstance(public_commit, str) or not SHA.fullmatch(public_commit)):
        raise ValueError('Historical audit application evidence is incomplete')
    try:
        _git(repo, 'merge-base', '--is-ancestor', public_commit, main_head)
    except ValueError as exc:
        raise ValueError('Historical audit publication is not in current main history') from exc
    request, request_meta = _json(repo, public_commit, RELEASE_REQUEST)
    public_receipt, receipt_meta = _json(repo, public_commit, PUBLIC_RECEIPT)
    public_raw, public_meta = _path_blob(repo, public_commit, 'data/papers.json')
    try:
        historical_public = json.loads(public_raw)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError('Historical public corpus is invalid') from exc
    live = application.get('live_verification') or {}
    removals, keeps = request.get('removals'), request.get('keeps')
    if (not isinstance(removals, list) or not isinstance(keeps, list) or not isinstance(historical_public, list)
        or any(not isinstance(x, dict) for x in removals+keeps)):
        raise ValueError('Historical audit inventories are incomplete')
    digest = hashlib.sha256(json.dumps({'removals':removals,'keeps':keeps}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    if (request.get('release_id') != RELEASE or request.get('publication_approved') is not True
        or public_receipt != saved or public_receipt.get('release_id') != RELEASE
        or public_receipt.get('removals') != removals or public_receipt.get('keeps') != keeps
        or request.get('records_sha256') != digest or public_receipt.get('records_sha256') != digest
        or public_receipt.get('removed') != len(removals) or public_receipt.get('audit_kept') != len(keeps)
        or application.get('audit_removals') != len(removals) or application.get('audit_keeps') != len(keeps)
        or len(historical_public) != public_receipt.get('records_after')
        or live.get('live_records') != len(historical_public)
        or hashlib.sha256(public_raw).hexdigest() != live.get('public_sha256')):
        raise ValueError('Historical audit request, receipt or public corpus evidence differs')
    completed = application.get('completed_job_ids')
    if not isinstance(completed, list) or any(not isinstance(x, str) or not x for x in completed) or len(completed) != len(set(completed)):
        raise ValueError('Historical completed-job inventory is invalid')
    index = {}
    for row in removals + keeps:
        candidate = row.get('candidate_id')
        if not isinstance(candidate, str) or not candidate or candidate in index:
            raise ValueError('Historical audit receipt candidate identity is ambiguous')
        index[candidate] = row
    original = current_plan(snapshot, confirmed_snapshot, manifests, public_records)
    checked = reconcile(snapshot, confirmed_snapshot, {k:v.get('records', []) for k,v in manifests.items()})
    decisions = {x['candidate_id']:x for x in checked['matched_decisions'] if x['collection'] == 'corpus-audit'}
    subs = {x['id']:x for x in snapshot['submissions']}
    rows = {x['candidate_id']:x for x in manifests['corpus-audit']['records']}
    outcomes = []
    for item in original['outcomes']:
        candidate = item['candidate_id']; decision = decisions.get(candidate); historic = index.get(candidate); row = rows.get(candidate)
        matched = bool(decision and historic and row and
            all(historic.get(k) == decision.get(k) for k in ('candidate_id','decision','submission_id','revision')) and
            historic.get('reviewed_content_sha256') == decision.get('content_sha256') and
            reviewed_digest(row) == decision.get('content_sha256') and
            historic.get('payload_hash') == subs[decision['submission_id']].get('payload_hash') and
            historic.get('public_record_sha256') == row.get('original_record_sha256') and
            historic.get('original_public_id') == row.get('original_public_id'))
        if matched and decision['decision'] == 'rejected':
            jobs = [j for j in snapshot['jobs'] if j.get('submission_id') == decision['submission_id'] and
                    j.get('candidate_id') == candidate and j.get('kind') == 'corpus_removal_review']
            matched = len(jobs) == 1 and jobs[0]['id'] in completed
        if matched:
            outcomes.append({'candidate_id':candidate,
                             'status':'historical_removal_receipted' if decision['decision']=='rejected' else 'historical_keep_receipted',
                             'current_publication_verified':False,'requires_live_public_recheck':True})
        else:
            outcomes.append(deepcopy(item))
    return {'status':'plan_only','outcomes':outcomes,'outcome_counts':dict(Counter(x['status'] for x in outcomes)),
            'historical_public_commit':public_commit,
            'evidence_blobs':[application_meta,saved_meta,request_meta,receipt_meta,public_meta],
            'publication_authorized':False,'current_publication_verified':False,'provider_requests':0,'writes':0,
            'requires_remote_lease_and_snapshot_recheck':True}

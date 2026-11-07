"""Call only the private ALEX worker services; never persist credentials.

This is a transport, not a scheduler or proof of processing. Read one bounded
JSON object from hidden stdin. A timeout or connection failure may follow a
write: report an unknown outcome and reconcile before any retry.
"""
from __future__ import annotations

import json
import re
import sys
import urllib.error
import urllib.request

from tools.content_review.site_reconcile_client import NoRedirect

ORIGIN = 'https://alex-research-review.neil-schwartzm917549.chatgpt.site'
PATHS = {'lease': '/api/content-review-lease', 'heartbeat': '/api/content-review-heartbeat',
         'soups_intake': '/api/content-review-soups-intake', 'no_work': '/api/content-review-no-work',
         'duplicate': '/api/content-review-duplicate', 'completion': '/api/content-review-completion',
         'source_request': '/api/content-review-source-request'}
MAX_INPUT = 16 * 1024 * 1024
MAX_RESULT = 16 * 1024
SAFE_REASON = re.compile(r'^[a-z_]{1,80}$')
SHA = re.compile(r'^[0-9a-f]{40}$')


def post(action, payload, token, *, opener=None):
    if action not in PATHS or not isinstance(payload, dict) or not isinstance(token, str) or not token or '\n' in token or '\r' in token:
        raise ValueError('Invalid Site worker request')
    try:
        body = json.dumps(payload, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf8')
    except (TypeError, ValueError, UnicodeError) as exc:
        raise ValueError('Invalid Site worker request') from exc
    if not 0 < len(body) <= MAX_INPUT:
        raise ValueError('Site worker request exceeds its bound')
    request = urllib.request.Request(ORIGIN + PATHS[action], data=body, method='POST',
        headers={'OAI-Sites-Authorization': 'Bearer ' + token, 'Content-Type': 'application/json', 'Accept': 'application/json'})
    try:
        with (opener or urllib.request.build_opener(NoRedirect)).open(request, timeout=55 if action in ('duplicate', 'completion') else 45) as response:
            status = response.status
            raw = response.read(MAX_RESULT + 1)
    except urllib.error.HTTPError as exc:
        status = exc.code
        raw = exc.read(MAX_RESULT + 1)
    except (OSError, TimeoutError):
        return {'status': 'outcome_unknown', 'action': action, 'reconcile_before_retry': True}
    try:
        if len(raw) > MAX_RESULT: raise ValueError('oversized')
        result = json.loads(raw)
    except (ValueError, UnicodeError):
        return {'status': 'outcome_unknown', 'action': action, 'reconcile_before_retry': True}
    if not isinstance(result, dict):
        return {'status': 'outcome_unknown', 'action': action, 'reconcile_before_retry': True}
    if status != 200 or result.get('status') != 'committed_and_read_back':
        reason = result.get('reason')
        reason = reason if isinstance(reason, str) and SAFE_REASON.fullmatch(reason) else 'site_response_unavailable'
        known_blocked = {'invalid_request', 'request_too_large', 'worker_not_verified', 'source_head_changed',
                         'proposal_expired', 'decisions_changed', 'service_access_required', 'lease_unavailable',
                         'heartbeat_unavailable', 'fence_not_idle', 'intake_unavailable', 'no_work_unavailable',
                         'duplicate_unavailable', 'completion_unavailable', 'source_reservation_unavailable'}
        uncertain = reason not in known_blocked or status >= 500
        return {'status': 'blocked' if not uncertain else 'outcome_unknown', 'action': action,
                'http_status': status, 'reason': reason, 'reconcile_before_retry': uncertain}
    commit = result.get('commit_sha') or result.get('heartbeat_head')
    if not isinstance(commit, str) or not SHA.fullmatch(commit):
        return {'status': 'outcome_unknown', 'action': action, 'reconcile_before_retry': True}
    output = {'status': 'committed_and_read_back', 'action': action, 'commit_sha': commit,
              'native_observation_authenticated': False}
    if action == 'soups_intake':
        count, receipt = result.get('candidate_count'), result.get('receipt_path')
        if (type(count) is not int or not 1 <= count <= 5 or not isinstance(receipt, str) or
            not re.fullmatch(r'config/content_review_intake_receipts/[0-9a-f]{64}\.json', receipt) or
            result.get('candidate_processing') is not False or result.get('publication_verified') is not False):
            return {'status': 'outcome_unknown', 'action': action, 'reconcile_before_retry': True}
        output.update(candidate_count=count, receipt_path=receipt, candidate_processing=False, publication_verified=False)
    elif action == 'no_work':
        receipt = result.get('receipt_path')
        if (not isinstance(receipt, str) or not re.fullmatch(r'config/content_review_run_receipts/[a-zA-Z0-9-]{1,100}\.json', receipt) or
            result.get('candidate_processing') is not False or result.get('publication_verified') is not False or
            result.get('native_completion_verified') is not False):
            return {'status': 'outcome_unknown', 'action': action, 'reconcile_before_retry': True}
        output.update(receipt_path=receipt, candidate_processing=False, native_completion_verified=False, publication_verified=False)
    elif action == 'duplicate':
        receipt = result.get('receipt_path')
        if (not isinstance(receipt, str) or not re.fullmatch(r'config/content_review_mechanical_checkpoints/[0-9a-f]{64}\.json', receipt) or
            result.get('gate') != 'duplicates' or result.get('candidate_processing') is not True or
            result.get('native_completion_verified') is not False or result.get('publication_verified') is not False):
            return {'status': 'outcome_unknown', 'action': action, 'reconcile_before_retry': True}
        output.update(receipt_path=receipt, gate='duplicates', candidate_processing=True,
                      native_completion_verified=False, publication_verified=False)
    elif action == 'completion':
        receipt = result.get('receipt_path')
        if (not isinstance(receipt, str) or not re.fullmatch(r'config/content_review_run_receipts/[a-zA-Z0-9-]{1,100}\.json', receipt) or
            result.get('candidate_processing') is not True or result.get('native_completion_verified') is not False or
            result.get('publication_verified') is not False):
            return {'status': 'outcome_unknown', 'action': action, 'reconcile_before_retry': True}
        output.update(receipt_path=receipt, candidate_processing=True, native_completion_verified=False, publication_verified=False)
    elif action == 'source_request':
        path, limit = result.get('request_path'), result.get('source_request_limit')
        if (not isinstance(path, str) or not re.fullmatch(r'config/content_review_source_requests/[0-9a-f]{64}\.json', path) or
            type(limit) is not int or not 1 <= limit <= 30 or result.get('source_request_reserved') is not True or
            result.get('source_workflow_verified') is not False or result.get('candidate_processing') is not False or
            result.get('publication_verified') is not False):
            return {'status': 'outcome_unknown', 'action': action, 'reconcile_before_retry': True}
        output.update(request_path=path, source_request_limit=limit, source_request_reserved=True,
                      source_workflow_verified=False, candidate_processing=False, publication_verified=False)
    return output


def main():
    raw = sys.stdin.buffer.readline(MAX_INPUT + 1)
    try:
        if len(raw) > MAX_INPUT: raise ValueError('Input exceeds bound')
        data = json.loads(raw)
        if not isinstance(data, dict) or set(data) != {'action', 'payload', 'site_token'}:
            raise ValueError('Input is invalid')
        result = post(data['action'], data['payload'], data['site_token'])
    except (ValueError, TypeError, UnicodeError):
        print(json.dumps({'status': 'blocked', 'reason': 'invalid_worker_request'}));return 1
    print(json.dumps(result, sort_keys=True))
    return 0 if result['status'] == 'committed_and_read_back' else 1


if __name__ == '__main__':
    raise SystemExit(main())

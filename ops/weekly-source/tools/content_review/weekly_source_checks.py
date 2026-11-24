"""Final weekly-only checks layered over the normal, leased source producer."""
import json
import re

from alex.editorial_exclusions import record_keys
from tools.content_review.d1_reconcile import _rows
from tools.content_review.source_worker import digest
from tools.content_review.verified_inputs import _git, _path_blob


def historical_requests(repo, head):
    """Index immutable requests, including failed or unaccounted reservations."""
    directory = 'config/content_review_source_requests'
    raw = _git(repo, 'ls-tree', '-r', '-z', '--name-only', head, '--', directory)
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError('Weekly source request history is too large')
    keys = set()
    for name in raw.rstrip(b'\0').split(b'\0') if raw else ():
        path = name.decode('ascii')
        if not re.fullmatch(directory + '/[0-9a-f]{64}\\.json', path):
            raise ValueError('Unexpected weekly source request history')
        body, _ = _path_blob(repo, head, path)
        request = json.loads(body)
        if not isinstance(request, dict):
            raise ValueError('Invalid source request history')
        request_id = request.pop('request_id', None)
        if request_id != path[-69:-5] or digest(request) != request_id:
            raise ValueError('Immutable source request hash mismatch')
        records = request.get('records')
        if not isinstance(records, list) or not 1 <= len(records) <= 5:
            raise ValueError('Invalid source request history')
        for record in records:
            if record['collection'] == 'weekly':
                keys.add((record['candidate_id'], record['content_sha256']))
    return keys


def editorial_guard(snapshot, confirmed, public, exclusions):
    drafts = _rows(snapshot, 'drafts')
    other = _rows(confirmed, 'drafts')
    if {r['id']: r for r in drafts} != {r['id']: r for r in other}:
        raise ValueError('Private drafts changed during source planning')
    draft_batches = {r['batch'] for r in drafts if r['collection'] == 'weekly'}
    blocked_ids = set()
    for row in drafts:
        if row['collection'] != 'weekly':
            continue
        hashes = json.loads(row['content_hashes'])
        rejected = json.loads(row['rejected_ids'])
        if not isinstance(hashes, dict) or not isinstance(rejected, list):
            raise ValueError('Weekly draft identities unavailable')
        blocked_ids.update(hashes)
        blocked_ids.update(rejected)

    public_keys = set().union(*(record_keys(r) for r in public))
    public_keys.update(exclusions)

    def reason(row):
        if (row.get('review_batch') or row.get('batch')) in draft_batches or row['candidate_id'] in blocked_ids:
            return 'weekly_candidate_has_private_draft'
        if row.get('publication_approved') or record_keys(row) & public_keys:
            return 'weekly_candidate_published_approved_or_excluded'
        return None
    return reason

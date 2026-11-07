"""Read and reconcile private Site decisions without persisting or logging rows.

This is a read-only preflight, not a scheduler, lease, candidate update or
publication authority. A writer must independently repeat the checks under a
live lease immediately before an expected-head commit.
"""
from collections import Counter
import json
from pathlib import Path
import re
import subprocess
import sys
import urllib.error
import urllib.request

from tools.content_review.d1_reconcile import reconcile
from tools.content_review.verified_inputs import load_inputs

SITE_URL = 'https://alex-research-review.neil-schwartzm917549.chatgpt.site/api/content-review-snapshot'
LIMIT = 8 * 1024 * 1024
REFS = {'refs/heads/main': 'main', 'refs/heads/codex/soups-corpus-review': 'review'}
SHA = re.compile(r'^[0-9a-f]{40}$')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, 'redirect refused', headers, fp)


def remote_heads(repo):
    try:
        result = subprocess.run(['git', '-C', str(repo), 'ls-remote', 'origin', *REFS],
                                capture_output=True, check=True, timeout=30, text=True)
    except (OSError, subprocess.SubprocessError) as exc:
        raise ValueError('Current source heads are unavailable') from exc
    heads = {}
    for line in result.stdout.splitlines():
        parts = line.split('\t')
        if len(parts) != 2 or parts[1] not in REFS or not SHA.fullmatch(parts[0]) or REFS[parts[1]] in heads:
            raise ValueError('Current source heads are invalid')
        heads[REFS[parts[1]]] = parts[0]
    if set(heads) != {'main', 'review'}:
        raise ValueError('Current source heads are incomplete')
    return heads


def read_snapshot(token, *, opener=None):
    if not isinstance(token, str) or not token or '\n' in token or '\r' in token:
        raise ValueError('Site service access is unavailable')
    request = urllib.request.Request(SITE_URL, headers={
        'OAI-Sites-Authorization': 'Bearer ' + token, 'Accept': 'application/json'})
    try:
        with (opener or urllib.request.build_opener(NoRedirect)).open(request, timeout=90) as response:
            if response.status != 200 or 'no-store' not in response.headers.get('Cache-Control', ''):
                raise ValueError('Site snapshot response is not usable')
            raw = response.read(LIMIT + 1)
        if len(raw) > LIMIT:
            raise ValueError('Site snapshot exceeds the bounded size')
        data = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError('Site snapshot read failed') from exc
    if (not isinstance(data, dict) or data.get('status') != 'complete_read_only'
        or data.get('transactional_snapshot') is not False or data.get('lease_verified') is not False
        or data.get('candidate_processing') is not False):
        raise ValueError('Site snapshot evidence is incomplete')
    return data['snapshot'], data['confirmed_snapshot']


def inspect(repo, token, *, heads_reader=remote_heads, snapshot_reader=read_snapshot, inputs_reader=load_inputs):
    """Return aggregate counts only; all private rows and digests stay in memory."""
    heads = heads_reader(repo)
    inputs = inputs_reader(repo, heads['review'], heads['main'])
    snapshot, confirmed = snapshot_reader(token)
    result = reconcile(snapshot, confirmed,
        {name: manifest.get('records', []) for name, manifest in inputs['reconciliation_manifests'].items()})
    if heads_reader(repo) != heads:
        raise ValueError('A source head changed during reconciliation')
    held = Counter(item['reason'] for item in result['held'])
    matched_collections = Counter(item['collection'] for item in result['matched_decisions'])
    held_collections = Counter(item['collection'] for item in result['held'])
    return {'status': 'read_only_reconciliation', 'counts': result['counts'],
            'held_by_reason': dict(sorted(held.items())), 'review_head': heads['review'],
            'matched_by_collection': dict(sorted(matched_collections.items())),
            'held_by_collection': dict(sorted(held_collections.items())),
            'main_head': heads['main'], 'transactional_snapshot': False,
            'lease_verified': False, 'candidate_processing': False,
            'requires_recheck_under_lease': True}


def main():
    token = sys.stdin.readline().rstrip('\r\n')
    try:
        result = inspect(Path.cwd(), token)
    except (ValueError, KeyError, TypeError):
        # Database values, identity information, tokens and provider messages
        # are never written to stdout/stderr, even on failure.
        print(json.dumps({'status': 'blocked', 'reason': 'read_only_reconciliation_failed'}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())

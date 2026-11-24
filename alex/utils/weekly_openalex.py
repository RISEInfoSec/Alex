"""Authenticated private recorder client for weekly search and DOI lookups."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit

import requests

GATEWAY = 'https://alex-research-review.neil-schwartzm917549.chatgpt.site/weekly-openalex'
SHA = re.compile(r'[0-9a-f]{40}')
HASH = re.compile(r'[0-9a-f]{64}')


class GatewayUnavailable(RuntimeError):
    """A bounded reason safe for an Actions log or a public checkpoint."""


def _oidc():
    url = os.environ.get('ACTIONS_ID_TOKEN_REQUEST_URL', '')
    bearer = os.environ.get('ACTIONS_ID_TOKEN_REQUEST_TOKEN')
    if not bearer or not url.startswith('https://'):
        raise GatewayUnavailable('openalex_github_identity_unavailable')
    response = requests.get(url, params={'audience': GATEWAY},
                            headers={'Authorization': 'Bearer ' + bearer},
                            timeout=15, allow_redirects=False)
    if response.status_code != 200:
        raise GatewayUnavailable('openalex_github_identity_unavailable')
    token = response.json().get('value')
    if not isinstance(token, str) or not 1 <= len(token) <= 16384:
        raise GatewayUnavailable('openalex_github_identity_invalid')
    return token


def reason(reply):
    detail = reply.get('reason')
    return detail if isinstance(detail, str) and re.fullmatch(r'[a-z_]{1,90}', detail) else reply['status']


def call(operation, *, deadline_seconds=90, **fields):
    bearer = os.environ.get('ALEX_SITE_SERVICE_BEARER')
    if not bearer:
        raise GatewayUnavailable('openalex_gateway_credential_missing')
    try:
        token = _oidc()
        if operation == 'key_proof':
            key = os.environ.get('OPENALEX_API_KEY')
            if not key:
                raise GatewayUnavailable('repository_openalex_binding_absent')
            context = 'alex-weekly-key-continuity-v1\n' + hashlib.sha256(token.encode()).hexdigest() + '\n'
            fields['proof'] = hmac.new(key.encode(), context.encode(), hashlib.sha256).hexdigest()
        response = requests.post(GATEWAY, headers={'OAI-Sites-Authorization': 'Bearer ' + bearer},
                                 json=dict(fields, operation=operation, identity_token=token),
                                 timeout=(10, max(1, min(deadline_seconds, 120))), allow_redirects=False)
        body = response.json()
        if not isinstance(body, dict) or not re.fullmatch(r'[a-z_]{1,80}', str(body.get('status', ''))):
            raise ValueError()
        return body
    except (requests.RequestException, ValueError, TypeError):
        # Never echo a URL, signed identity, request contents or raw error. The
        # recorder must reconcile a lost POST response before any further send.
        raise GatewayUnavailable('openalex_gateway_outcome_unknown') from None


class WeeklyRecorder:
    def __init__(self, window, base_file: Path):
        self.window = dict(window)
        self.base_file = base_file
        self.confirmed_head = None

    def request(self, url, params, seconds_left):
        head = self.base_file.read_text().strip()
        if not SHA.fullmatch(head):
            raise GatewayUnavailable('openalex_series_head_unverified')
        fields = {'end': self.window['until_date'], 'head': head}
        def invoke(operation, **extra):
            remaining = seconds_left()
            if remaining < 25:
                raise GatewayUnavailable('runtime_budget')
            return call(operation, deadline_seconds=remaining, **fields, **extra)

        path = urlsplit(url).path
        if path == '/works':
            item = {'kind': 'search', 'query': params['search'], 'page': params['page'],
                    'per_page': params['per-page'], **self.window}
        elif path.startswith('/works/https://doi.org/'):
            item = {'kind': 'doi', 'doi': path.removeprefix('/works/https://doi.org/')}
        else:
            raise GatewayUnavailable('openalex_request_outside_series')
        if self.confirmed_head != head:
            prepared = invoke('prepare_snapshot')
            if prepared['status'] == 'snapshot_prepared':
                seq, digest = prepared.get('sequence'), prepared.get('sha256')
                if type(seq) is not int or seq < 0 or not HASH.fullmatch(str(digest)):
                    raise GatewayUnavailable('openalex_snapshot_unverified')
                prepared = invoke('confirm_snapshot', ack={'sequence':seq, 'sha256':digest})
            if prepared['status'] != 'snapshot_confirmed':
                raise GatewayUnavailable('openalex_' + reason(prepared))
            self.confirmed_head = head
        return invoke('request', item=item)


if __name__ == '__main__':
    reply = call('key_proof')
    print(json.dumps({k:reply.get(k) for k in ('status', 'reason', 'keys_match', 'installed_secrets',
                                               'repository_key_configured', 'provider_attempts')}, sort_keys=True))
    if reply['status'] != 'key_verified' or reply.get('keys_match') is not True:
        raise SystemExit(1)

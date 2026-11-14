"""Offline candidate for a read-only workflow identity check.

The Site independently verifies the signed identity and source heads. This
probe cannot enable provider sends, clear a hold, or write review data.
Credentials and identity tokens remain in process memory only.
"""
from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

ORIGIN = 'https://alex-research-review.neil-schwartzm917549.chatgpt.site'
PATH = '/api/private-openalex-writer-identity'
SHA = re.compile(r'^[a-f0-9]{40}$')
RUN = re.compile(r'^[1-9][0-9]{0,15}$')


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def check_identity(env, opener=None):
    """Return only a safe status; never expose URLs, tokens or exception text."""
    try:
        run = env.get('GITHUB_RUN_ID', '')
        trigger = env.get('GITHUB_SHA', '')
        main = env.get('ALEX_CHECKOUT_HEAD', '')
        state = env.get('ALEX_PIPELINE_STATE_HEAD', '')
        site_bearer = env.get('ALEX_SITE_SERVICE_BEARER', '')
        request_bearer = env.get('ACTIONS_ID_TOKEN_REQUEST_TOKEN', '')
        endpoint = urllib.parse.urlsplit(env.get('ACTIONS_ID_TOKEN_REQUEST_URL', ''))
        host = (endpoint.hostname or '').lower()
        if (not RUN.fullmatch(run) or not SHA.fullmatch(trigger) or not SHA.fullmatch(main) or not SHA.fullmatch(state)
                or not site_bearer or not request_bearer or len(site_bearer) > 4096
                or len(request_bearer) > 4096 or any(c in site_bearer + request_bearer for c in '\r\n')
                or endpoint.scheme != 'https' or not host.endswith('.actions.githubusercontent.com')
                or endpoint.username is not None or endpoint.password is not None
                or endpoint.port not in (None, 443) or endpoint.fragment):
            return {'status': 'unavailable', 'provider_access_authorized': False}
        query = urllib.parse.parse_qsl(endpoint.query, keep_blank_values=True)
        if any(k == 'audience' for k, _ in query):
            return {'status': 'unavailable', 'provider_access_authorized': False}
        query.append(('audience', ORIGIN + PATH))
        url = urllib.parse.urlunsplit((endpoint.scheme, endpoint.netloc, endpoint.path,
                                      urllib.parse.urlencode(query), ''))
        client = opener or urllib.request.build_opener(NoRedirect())
        request = urllib.request.Request(url, headers={'Authorization': 'Bearer ' + request_bearer})
        with client.open(request, timeout=15) as response:
            if response.status != 200:
                return {'status': 'unavailable', 'provider_access_authorized': False}
            raw = response.read(32769)
        if len(raw) > 32768:
            return {'status': 'unavailable', 'provider_access_authorized': False}
        issued = json.loads(raw)
        token = issued.get('value') if isinstance(issued, dict) else None
        if not isinstance(token, str) or not token or len(token) > 16384:
            return {'status': 'unavailable', 'provider_access_authorized': False}
        payload = json.dumps({'identity_token': token, 'run_id': run, 'main': main,
                              'pipeline_state': state}, separators=(',', ':')).encode()
        request = urllib.request.Request(ORIGIN + PATH, data=payload, method='POST', headers={
            'OAI-Sites-Authorization': 'Bearer ' + site_bearer, 'Content-Type': 'application/json'})
        with client.open(request, timeout=20) as response:
            if response.status != 200:
                return {'status': 'unavailable', 'provider_access_authorized': False}
            raw = response.read(4097)
        if len(raw) > 4096:
            return {'status': 'unavailable', 'provider_access_authorized': False}
        result = json.loads(raw)
        if result != {'identity_verified': True, 'provider_access_authorized': False}:
            return {'status': 'unavailable', 'provider_access_authorized': False}
        return {'status': 'identity_verified', 'provider_access_authorized': False}
    except Exception:
        return {'status': 'unavailable', 'provider_access_authorized': False}


if __name__ == '__main__':
    result = check_identity(os.environ)
    if result['status'] == 'identity_verified':
        print('Private workflow identity verified; provider access remains held.')
        sys.exit(0)
    print('Private workflow identity unavailable; provider access remains held.')
    sys.exit(1)

"""One-shot GitHub Actions canary client. No OpenAlex request is made.

This staged client accepts no source rows, provider key or response fixture.
Its signed job identity is obtained for the dedicated canary audience. A
possibly committed write is reconciled by one separately authenticated read;
the write itself is never retried.
"""
from __future__ import annotations

import json
import os
import re
import signal
import sys
import urllib.error
import urllib.parse
import urllib.request

RELAY = 'https://alex-recorder-relay.neil-schwartzm917549.chatgpt.site/api/private-openalex-canary'
AUDIENCE = 'https://alex-research-review.neil-schwartzm917549.chatgpt.site/api/private-openalex-canary'
HASH = re.compile(r'^[a-f0-9]{64}$')


class HardDeadline(BaseException):
    """A whole-process deadline must not be converted into a retry/read."""


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise urllib.error.HTTPError(req.full_url, code, 'redirect_refused', headers, fp)


def _read(client, request, timeout, limit=8192):
    with client.open(request, timeout=timeout) as response:
        if response.status != 200:
            raise ValueError('unavailable')
        raw = response.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('unavailable')
    return json.loads(raw)


def _valid(value, status):
    return (isinstance(value, dict) and set(value) == {'status', 'evidence_kind', 'evidence_sha256',
            'provider_access_authorized', 'global_fence_verified'} and value['status'] == status
            and value['evidence_kind'] == 'synthetic_no_network_v1'
            and isinstance(value['evidence_sha256'], str) and HASH.fullmatch(value['evidence_sha256']) is not None
            and value['provider_access_authorized'] is False and value['global_fence_verified'] is False)


def run(env, *, opener=None, read_only=False, trace=None):
    trace = trace if trace is not None else {}
    trace['stage'] = 'preflight'
    credential = env.get('ACTIONS_ID_TOKEN_REQUEST_TOKEN', '')
    bearer = env.get('ALEX_RECORDER_RELAY_BEARER', '')
    endpoint = urllib.parse.urlsplit(env.get('ACTIONS_ID_TOKEN_REQUEST_URL', ''))
    trace.update({'oidc_credential_present': bool(credential), 'relay_credential_present': bool(bearer),
                  'oidc_credential_length_ok': len(credential.encode('utf-8')) <= 65536, 'relay_credential_length_ok': len(bearer) <= 4096,
                  'credentials_single_line': not any(c in credential + bearer for c in '\r\n'),
                  'oidc_https': endpoint.scheme == 'https', 'oidc_no_userinfo': endpoint.username is None and endpoint.password is None,
                  'oidc_port_allowed': endpoint.port in (None, 443), 'oidc_no_fragment': not endpoint.fragment,
                  'oidc_host_allowed': (endpoint.hostname or '').lower().endswith('.actions.githubusercontent.com')})
    if (not credential or not bearer or len(credential.encode('utf-8')) > 65536 or len(bearer) > 4096
            or any(c in credential + bearer for c in '\r\n') or endpoint.scheme != 'https'
            or not (endpoint.hostname or '').lower().endswith('.actions.githubusercontent.com')
            or endpoint.username is not None or endpoint.password is not None
            or endpoint.port not in (None, 443) or endpoint.fragment):
        raise ValueError('unavailable')
    query = urllib.parse.parse_qsl(endpoint.query, keep_blank_values=True)
    trace['oidc_audience_absent'] = not any(key == 'audience' for key, _ in query)
    if any(key == 'audience' for key, _ in query):
        raise ValueError('unavailable')
    query.append(('audience', AUDIENCE))
    url = urllib.parse.urlunsplit((endpoint.scheme, endpoint.netloc, endpoint.path, urllib.parse.urlencode(query), ''))
    client = opener or urllib.request.build_opener(NoRedirect())
    trace['stage'] = 'oidc'
    issued = _read(client, urllib.request.Request(url, headers={'Authorization': 'Bearer ' + credential}), 15, limit=32768)
    token = issued.get('value') if isinstance(issued, dict) else None
    if not isinstance(token, str) or not token or len(token) > 16384:
        raise ValueError('unavailable')

    def operation(op):
        body = json.dumps({'op': op, 'identity_token': token}, separators=(',', ':')).encode()
        req = urllib.request.Request(RELAY, data=body, method='POST',
            headers={'OAI-Sites-Authorization': 'Bearer ' + bearer, 'Content-Type': 'application/json'})
        return _read(client, req, 100)

    if read_only:
        trace['stage'] = 'read_only'
        observed = operation('read')
        if observed == {'status': 'not_available', 'provider_access_authorized': False}:
            return {'status': 'canary_read_ready', 'provider_access_authorized': False, 'global_fence_verified': False}
        if _valid(observed, 'canary_verified'):
            return {'status': 'canary_read_verified', 'provider_access_authorized': False, 'global_fence_verified': False}
        raise ValueError('unavailable')

    # If a response is lost, an independent read can confirm the immutable
    # record. Neither a timeout nor a malformed result causes another write.
    trace['stage'] = 'write'
    try:
        written = operation('write')
        if not _valid(written, 'canary_recorded'):
            written = None
            trace['write_result'] = 'unexpected_response'
    except Exception as exc:
        trace['write_result'] = 'http_' + str(exc.code) if isinstance(exc, urllib.error.HTTPError) else 'uncertain'
        written = None
    trace['stage'] = 'readback'
    readback = operation('read')
    if not _valid(readback, 'canary_verified'):
        raise ValueError('reconciliation_required')
    if written is not None and written['evidence_sha256'] != readback['evidence_sha256']:
        raise ValueError('reconciliation_required')
    return {'status': 'canary_verified', 'write_response_confirmed': written is not None,
            'provider_access_authorized': False, 'global_fence_verified': False}


def _deadline(*_args):
    raise HardDeadline('deadline')


if __name__ == '__main__':
    trace = {}
    try:
        signal.signal(signal.SIGALRM, _deadline)
        signal.alarm(230)
        if sys.argv[1:] not in ([], ['--read-only']):
            raise ValueError('invalid')
        print(json.dumps(run(os.environ, read_only=sys.argv[1:] == ['--read-only'], trace=trace), sort_keys=True, separators=(',', ':')))
    except BaseException as exc:
        error = 'http_' + str(exc.code) if isinstance(exc, urllib.error.HTTPError) else type(exc).__name__
        if error not in ('ValueError', 'TimeoutError', 'HardDeadline', 'URLError') and not re.fullmatch(r'http_[1-5][0-9][0-9]', error):
            error = 'unavailable'
        safe = {key: value for key, value in trace.items() if key not in ('stage', 'write_result') and isinstance(value, bool)}
        print(json.dumps({'status': 'canary_unavailable_or_reconciliation_required', 'stage': trace.get('stage', 'setup'),
                          'write_result': trace.get('write_result', 'not_attempted'), 'error': error, 'checks': safe}, sort_keys=True, separators=(',', ':')))
        sys.exit(1)

import requests
from unittest.mock import MagicMock

from alex.utils import http
from alex.utils.http import _ProviderGuardedSession


class RedirectAdapter(requests.adapters.BaseAdapter):
    def __init__(self, destination):
        self.destination = destination
        self.sent = []

    def send(self, request, **kwargs):
        self.sent.append(request.url)
        response = requests.Response()
        response.url = request.url
        response.request = request
        if len(self.sent) == 1:
            response.status_code = 302
            response.headers['Location'] = self.destination
        else:
            response.status_code = 200
            response._content = b'{}'
        return response

    def close(self):
        pass


def test_other_source_redirect_cannot_send_to_openalex():
    session = _ProviderGuardedSession()
    adapter = RedirectAdapter('https://api.openalex.org/works')
    session.mount('https://', adapter)
    try:
        session.get('https://source.example/works')
        assert False, 'the redirect must fail before an OpenAlex send'
    except requests.exceptions.RequestException as exc:
        assert str(exc) == 'OpenAlex requires the shared private coordinator'
    assert adapter.sent == ['https://source.example/works']


def test_unrelated_source_redirects_still_work():
    session = _ProviderGuardedSession()
    adapter = RedirectAdapter('https://source.example/next')
    session.mount('https://', adapter)
    assert session.get('https://source.example/works').status_code == 200
    assert adapter.sent == ['https://source.example/works', 'https://source.example/next']


def test_direct_openalex_redirect_is_not_followed_or_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(http, 'CACHE', tmp_path / 'cache.json')
    # This legacy transport test uses a fake response. The production fence is
    # separately checked without bypass in test_main_openalex_shared_fence.py.
    monkeypatch.setattr(http, '_shared_coordinator_unavailable', lambda: False)
    monkeypatch.setattr(http, '_openalex_policy', lambda: {
        'requests_enabled': True, 'min_interval_seconds': 0,
        'request_timeout_seconds': 20, 'failure_cooldown_seconds': 3600,
        'retry_not_before': None, 'max_openalex_requests_per_run': 13,
    })
    monkeypatch.setattr(http.time, 'sleep', lambda _: None)
    client = http.HttpClient()
    redirected = MagicMock(status_code=302, headers={})
    redirected.json.return_value = {'must_not_be_cached': True}
    client.session.get = MagicMock(return_value=redirected)
    assert client.get_json('https://api.openalex.org/works') is None
    assert client.session.get.call_args.kwargs['allow_redirects'] is False
    assert client.get_json('https://api.openalex.org/works', {'next': 1}) is None
    assert client.session.get.call_count == 1
    assert client.openalex_deferred()

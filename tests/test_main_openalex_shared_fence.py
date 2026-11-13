import json
from unittest.mock import Mock

import pytest
import requests

from alex.utils import http
from alex.utils.discovery_checkpoint import DiscoveryClient, DiscoveryIncomplete


@pytest.mark.parametrize('url', [
    'https://api.openalex.org/works', 'https://api.openalex.org./works',
    'https://openalex.org/works', 'https://other.openalex.org/works',
])
def test_uncached_openalex_never_sends_even_when_policy_is_enabled(tmp_path, monkeypatch, url):
    monkeypatch.setattr(http, 'CACHE', tmp_path / 'cache.json')
    monkeypatch.setattr(http, '_openalex_policy', lambda: {'requests_enabled': True})
    client = http.HttpClient()
    client.session.get = Mock(side_effect=AssertionError('provider request forbidden'))
    with pytest.raises(http.ProviderCoordinationRequired, match='shared private coordinator'):
        client.get_json(url)
    client.session.get.assert_not_called()
    assert client.openalex_deferred()
    assert not (tmp_path / 'cache.json.openalex-policy').exists()


def test_existing_cached_response_is_available_without_a_provider_request(tmp_path, monkeypatch):
    monkeypatch.setattr(http, 'CACHE', tmp_path / 'cache.json')
    client = http.HttpClient()
    url = 'https://api.openalex.org/works'
    key = json.dumps({'url': url, 'params': {}, 'headers': {}}, sort_keys=True)
    client.cache[key] = {'results': [{'title': 'fixture'}]}
    client.session.get = Mock(side_effect=AssertionError('provider request forbidden'))
    assert client.get_json(url) == {'results': [{'title': 'fixture'}]}
    client.session.get.assert_not_called()


def test_other_source_redirect_does_not_bypass_the_shared_fence():
    class Redirect(requests.adapters.BaseAdapter):
        def __init__(self): self.sent = []
        def send(self, request, **kwargs):
            self.sent.append(request.url)
            response = requests.Response(); response.url = request.url; response.request = request
            response.status_code = 302; response.headers['Location'] = 'https://api.openalex.org/works'
            return response
        def close(self): pass
    session = http._ProviderGuardedSession(); adapter = Redirect(); session.mount('https://', adapter)
    with pytest.raises(http.ProviderCoordinationRequired):
        session.get('https://source.example/works')
    assert adapter.sent == ['https://source.example/works']


def test_http_client_propagates_a_blocked_redirect_without_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(http, 'CACHE', tmp_path / 'cache.json')
    monkeypatch.setattr(http.time, 'sleep', lambda _: None)
    client=http.HttpClient()
    client.session.get=Mock(side_effect=http.ProviderCoordinationRequired('held redirect'))
    with pytest.raises(http.ProviderCoordinationRequired):
        client.get_json('https://source.example/works')
    assert client.session.get.call_count==1


def test_private_legacy_entry_point_also_requires_shared_coordination(tmp_path, monkeypatch):
    monkeypatch.setattr(http, 'CACHE', tmp_path / 'cache.json')
    client=http.HttpClient();client.session.get=Mock(side_effect=AssertionError('provider request forbidden'))
    with pytest.raises(http.ProviderCoordinationRequired):
        client._openalex_request('https://api.openalex.org/works',None,None,30)
    client.session.get.assert_not_called()


def test_discovery_records_a_hold_and_never_a_successful_empty_result(tmp_path, monkeypatch):
    monkeypatch.setattr(http, 'CACHE', tmp_path / 'cache.json')
    monkeypatch.delenv('ALEX_DISCOVERY_SYNC', raising=False)
    client = DiscoveryClient(tmp_path / 'state.json', {'from_date': '2026-01-01', 'until_date': '2026-01-02'},
                             {'queries': ['fixture']}, {'runtime_seconds': 60, 'max_requests': 2, 'openalex_max_requests': 1})
    client.session.get = Mock(side_effect=AssertionError('provider request forbidden'))
    assert client.run_task('OpenAlex:fixture', lambda: client.get_json('https://api.openalex.org/works')) == []
    with pytest.raises(DiscoveryIncomplete):
        client.finish(tmp_path / 'receipt.json', 0)
    receipt = json.loads((tmp_path / 'receipt.json').read_text())
    assert receipt['status'] == 'deferred'
    assert receipt['deferred_tasks']['OpenAlex:fixture'] == 'openalex_shared_coordinator_required'
    assert receipt['actual_request_count'] == receipt['openalex_request_count'] == 0
    client.session.get.assert_not_called()


def test_apwg_does_not_turn_a_coordination_hold_into_a_lookup_miss(monkeypatch):
    from alex.pipelines import apwg_import
    monkeypatch.setattr(apwg_import.openalex, 'search', Mock(side_effect=http.ProviderCoordinationRequired('held')))
    with pytest.raises(http.ProviderCoordinationRequired):
        apwg_import.enrich_openalex(Mock(_host_blocked=Mock(return_value=False), openalex_deferred=Mock(return_value=False)),
                                    [{'title': 'Fixture', 'apwg_year': 2024}], 1)

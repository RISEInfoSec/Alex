import json
from unittest.mock import Mock

import pytest

from scripts.harvest_osint_metadata import CachedHTTPClient, ProviderCoordinationRequired


def test_uncached_openalex_is_blocked_without_sending_or_changing_cache(tmp_path):
    client = CachedHTTPClient(tmp_path / 'cache.json')
    client.session.get = Mock()
    with pytest.raises(ProviderCoordinationRequired):
        client.get_json('https://api.openalex.org/works', {'search': 'example'})
    client.session.get.assert_not_called()
    assert not client.cache_path.exists()


def test_cached_openalex_remains_readable_without_network(tmp_path):
    path = tmp_path / 'cache.json'
    key = json.dumps({'url': 'https://api.openalex.org/works', 'params': {}}, sort_keys=True)
    path.write_text(json.dumps({key: {'results': []}}))
    client = CachedHTTPClient(path)
    client.session.get = Mock()
    assert client.get_json('https://api.openalex.org/works') == {'results': []}
    client.session.get.assert_not_called()


def test_redirect_is_not_followed_or_cached(tmp_path):
    client = CachedHTTPClient(tmp_path / 'cache.json')
    client.session.get = Mock(return_value=Mock(status_code=302))
    with pytest.raises(ProviderCoordinationRequired):
        client.get_json('https://api.crossref.org/works')
    assert client.session.get.call_args.kwargs['allow_redirects'] is False
    assert not client.cache_path.exists()

import json
from pathlib import Path
from unittest.mock import patch, MagicMock
from alex.utils.http import HttpClient


class TestHttpClientCache:
    def test_successful_response_is_cached(self, tmp_path):
        cache_path = tmp_path / ".alex_cache.json"
        with patch("alex.utils.http.CACHE", cache_path), \
             patch("alex.utils.http.time.sleep"):
            client = HttpClient()
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"results": [1, 2]}
            with patch.object(client.session, "get", return_value=mock_resp):
                result = client.get_json("https://example.com/api", params={"q": "test"})
            assert result == {"results": [1, 2]}
            # Second call should use cache
            with patch.object(client.session, "get") as mock_get:
                result2 = client.get_json("https://example.com/api", params={"q": "test"})
                mock_get.assert_not_called()
            assert result2 == {"results": [1, 2]}

    def test_failed_response_is_not_cached(self, tmp_path):
        cache_path = tmp_path / ".alex_cache.json"
        with patch("alex.utils.http.CACHE", cache_path), \
             patch("alex.utils.http.time.sleep"):
            client = HttpClient()
            mock_resp = MagicMock()
            mock_resp.status_code = 500
            import requests as req
            mock_resp.raise_for_status.side_effect = req.exceptions.HTTPError("Server error")
            with patch.object(client.session, "get", return_value=mock_resp):
                result = client.get_json("https://example.com/api")
            assert result is None
            # Cache should NOT contain the None entry
            assert len(client.cache) == 0

    def test_network_error_is_not_cached(self, tmp_path):
        cache_path = tmp_path / ".alex_cache.json"
        with patch("alex.utils.http.CACHE", cache_path), \
             patch("alex.utils.http.time.sleep"):
            client = HttpClient()
            import requests as req
            with patch.object(client.session, "get", side_effect=req.exceptions.ConnectionError("timeout")):
                result = client.get_json("https://example.com/api")
            assert result is None
            assert len(client.cache) == 0

    def test_cache_persists_to_disk(self, tmp_path):
        cache_path = tmp_path / ".alex_cache.json"
        with patch("alex.utils.http.CACHE", cache_path), \
             patch("alex.utils.http.time.sleep"):
            client = HttpClient()
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"data": "value"}
            with patch.object(client.session, "get", return_value=mock_resp):
                client.get_json("https://example.com/api")
            assert cache_path.exists()
            saved = json.loads(cache_path.read_text())
            assert len(saved) == 1

    def test_loads_existing_cache(self, tmp_path):
        cache_path = tmp_path / ".alex_cache.json"
        key = json.dumps({"url": "https://example.com/api", "params": {}, "headers": {}}, sort_keys=True)
        cache_path.write_text(json.dumps({key: {"cached": True}}))
        with patch("alex.utils.http.CACHE", cache_path), \
             patch("alex.utils.http.time.sleep"):
            client = HttpClient()
            result = client.get_json("https://example.com/api")
        assert result == {"cached": True}

    def test_purges_legacy_none_entries(self, tmp_path):
        cache_path = tmp_path / ".alex_cache.json"
        key = json.dumps({"url": "https://example.com/stale", "params": {}, "headers": {}}, sort_keys=True)
        cache_path.write_text(json.dumps({key: None}))
        with patch("alex.utils.http.CACHE", cache_path), \
             patch("alex.utils.http.time.sleep"):
            client = HttpClient()
        assert len(client.cache) == 0
        saved = json.loads(cache_path.read_text())
        assert len(saved) == 0

    def test_malformed_json_response_not_cached(self, tmp_path):
        cache_path = tmp_path / ".alex_cache.json"
        with patch("alex.utils.http.CACHE", cache_path), \
             patch("alex.utils.http.time.sleep"):
            client = HttpClient()
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status.return_value = None
            mock_resp.json.side_effect = ValueError("Invalid JSON")
            with patch.object(client.session, "get", return_value=mock_resp):
                result = client.get_json("https://example.com/api")
            assert result is None
            assert len(client.cache) == 0

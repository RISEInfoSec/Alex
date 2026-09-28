import json
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


class TestGetRaw:
    def test_returns_text_and_caches(self, tmp_path):
        cache_path = tmp_path / ".alex_cache.json"
        with patch("alex.utils.http.CACHE", cache_path), \
             patch("alex.utils.http.time.sleep"):
            client = HttpClient()
            mock_resp = MagicMock()
            mock_resp.text = "<rss><channel></channel></rss>"
            mock_resp.raise_for_status = MagicMock()
            with patch.object(client.session, "get", return_value=mock_resp):
                result = client.get_raw("https://example.com/rss")
            assert result == "<rss><channel></channel></rss>"
            # Second call hits cache
            with patch.object(client.session, "get") as mock_get:
                result2 = client.get_raw("https://example.com/rss")
                mock_get.assert_not_called()
            assert result2 == "<rss><channel></channel></rss>"

    def test_failure_returns_none_not_cached(self, tmp_path):
        cache_path = tmp_path / ".alex_cache.json"
        with patch("alex.utils.http.CACHE", cache_path), \
             patch("alex.utils.http.time.sleep"):
            client = HttpClient()
            import requests as req
            with patch.object(client.session, "get", side_effect=req.exceptions.ConnectionError("fail")):
                result = client.get_raw("https://example.com/rss")
            assert result is None
            assert len(client.cache) == 0

    def test_cache_key_distinct_from_get_json(self, tmp_path):
        cache_path = tmp_path / ".alex_cache.json"
        with patch("alex.utils.http.CACHE", cache_path), \
             patch("alex.utils.http.time.sleep"):
            client = HttpClient()
            mock_resp = MagicMock()
            mock_resp.text = "raw text"
            mock_resp.raise_for_status = MagicMock()
            mock_resp.json.return_value = {"json": True}
            with patch.object(client.session, "get", return_value=mock_resp):
                raw = client.get_raw("https://example.com/api")
                js = client.get_json("https://example.com/api")
            assert raw == "raw text"
            assert js == {"json": True}
            assert len(client.cache) == 2


class TestHttpClientRetry:
    """Retry on 429 / 5xx with exponential backoff."""

    def _resp(self, status_code: int, body=None, headers=None):
        r = MagicMock()
        r.status_code = status_code
        r.headers = headers or {}
        if body is not None:
            r.json.return_value = body
        if status_code >= 400:
            import requests as req
            r.raise_for_status.side_effect = req.exceptions.HTTPError(f"{status_code} Error")
        else:
            r.raise_for_status = MagicMock()
        return r

    def test_retries_on_429_then_succeeds(self, tmp_path):
        cache_path = tmp_path / ".alex_cache.json"
        with patch("alex.utils.http.CACHE", cache_path), \
             patch("alex.utils.http.time.sleep") as sleep_mock:
            client = HttpClient()
            ok = self._resp(200, body={"ok": True})
            sequence = [self._resp(429), self._resp(429), ok]
            with patch.object(client.session, "get", side_effect=sequence) as get_mock:
                result = client.get_json("https://example.com/api")
            assert result == {"ok": True}
            assert get_mock.call_count == 3
            # Two backoff sleeps + one polite delay = at least 3 sleeps
            assert sleep_mock.call_count >= 3

    def test_retries_on_500_then_succeeds(self, tmp_path):
        cache_path = tmp_path / ".alex_cache.json"
        with patch("alex.utils.http.CACHE", cache_path), \
             patch("alex.utils.http.time.sleep"):
            client = HttpClient()
            ok = self._resp(200, body={"ok": True})
            sequence = [self._resp(500), ok]
            with patch.object(client.session, "get", side_effect=sequence) as get_mock:
                result = client.get_json("https://example.com/api")
            assert result == {"ok": True}
            assert get_mock.call_count == 2

    def test_does_not_retry_on_404(self, tmp_path):
        cache_path = tmp_path / ".alex_cache.json"
        with patch("alex.utils.http.CACHE", cache_path), \
             patch("alex.utils.http.time.sleep"):
            client = HttpClient()
            with patch.object(client.session, "get",
                              return_value=self._resp(404)) as get_mock:
                result = client.get_json("https://example.com/api")
            assert result is None
            assert get_mock.call_count == 1  # no retries on 4xx other than 429

    def test_gives_up_after_max_attempts(self, tmp_path):
        cache_path = tmp_path / ".alex_cache.json"
        with patch("alex.utils.http.CACHE", cache_path), \
             patch("alex.utils.http.time.sleep"):
            client = HttpClient()
            with patch.object(client.session, "get",
                              return_value=self._resp(503)) as get_mock:
                result = client.get_json("https://example.com/api")
            assert result is None
            assert get_mock.call_count == 3  # attempt + 2 retries

    def test_honours_retry_after_header(self, tmp_path):
        cache_path = tmp_path / ".alex_cache.json"
        with patch("alex.utils.http.CACHE", cache_path), \
             patch("alex.utils.http.time.sleep") as sleep_mock:
            client = HttpClient()
            ok = self._resp(200, body={"ok": True})
            sequence = [self._resp(429, headers={"Retry-After": "7"}), ok]
            with patch.object(client.session, "get", side_effect=sequence):
                client.get_json("https://example.com/api")
            sleep_args = [c.args[0] for c in sleep_mock.call_args_list if c.args]
            assert 7.0 in sleep_args  # explicit Retry-After honoured

    def test_retries_on_connection_error(self, tmp_path):
        cache_path = tmp_path / ".alex_cache.json"
        with patch("alex.utils.http.CACHE", cache_path), \
             patch("alex.utils.http.time.sleep"):
            client = HttpClient()
            import requests as req
            ok = self._resp(200, body={"ok": True})
            sequence = [
                req.exceptions.ConnectionError("net flake"),
                ok,
            ]
            with patch.object(client.session, "get", side_effect=sequence) as get_mock:
                result = client.get_json("https://example.com/api")
            assert result == {"ok": True}
            assert get_mock.call_count == 2


class TestHttpClientRetryAfterCap:
    """A Retry-After beyond the cap skips the host instead of stalling the job."""

    _resp = TestHttpClientRetry._resp

    def test_long_retry_after_skips_without_sleeping(self, tmp_path):
        cache_path = tmp_path / ".alex_cache.json"
        with patch("alex.utils.http.CACHE", cache_path), \
             patch("alex.utils.http.time.sleep") as sleep_mock:
            client = HttpClient()
            long_wait = self._resp(429, headers={"Retry-After": "36000"})
            with patch.object(client.session, "get", return_value=long_wait) as get_mock:
                result = client.get_json("https://api.openalex.org/works")
            assert result is None
            assert get_mock.call_count == 1  # no retry against a 10h wait
            sleep_args = [c.args[0] for c in sleep_mock.call_args_list if c.args]
            assert all(s <= 60 for s in sleep_args)

    def test_blocked_host_short_circuits_later_requests(self, tmp_path):
        cache_path = tmp_path / ".alex_cache.json"
        with patch("alex.utils.http.CACHE", cache_path), \
             patch("alex.utils.http.time.sleep"):
            client = HttpClient()
            long_wait = self._resp(429, headers={"Retry-After": "36000"})
            with patch.object(client.session, "get", return_value=long_wait) as get_mock:
                client.get_json("https://api.openalex.org/works", params={"q": "a"})
                assert client.get_json("https://api.openalex.org/works", params={"q": "b"}) is None
                assert client.get_raw("https://api.openalex.org/works", params={"q": "c"}) is None
            assert get_mock.call_count == 1  # host blocked after the first long 429

    def test_block_is_per_host(self, tmp_path):
        cache_path = tmp_path / ".alex_cache.json"
        with patch("alex.utils.http.CACHE", cache_path), \
             patch("alex.utils.http.time.sleep"):
            client = HttpClient()
            long_wait = self._resp(429, headers={"Retry-After": "36000"})
            ok = self._resp(200, body={"ok": True})
            with patch.object(client.session, "get", side_effect=[long_wait, ok]):
                client.get_json("https://api.openalex.org/works")
                assert client.get_json("https://api.crossref.org/works") == {"ok": True}

    def test_block_expires(self, tmp_path):
        cache_path = tmp_path / ".alex_cache.json"
        with patch("alex.utils.http.CACHE", cache_path), \
             patch("alex.utils.http.time.sleep"), \
             patch("alex.utils.http.time.monotonic", side_effect=[1000.0, 1000.0 + 36001]):
            client = HttpClient()
            long_wait = self._resp(429, headers={"Retry-After": "36000"})
            ok = self._resp(200, body={"ok": True})
            with patch.object(client.session, "get", side_effect=[long_wait, ok]):
                client.get_json("https://api.openalex.org/works", params={"q": "a"})
                assert client.get_json("https://api.openalex.org/works", params={"q": "b"}) == {"ok": True}

    def test_retry_after_at_cap_is_still_honoured(self, tmp_path):
        cache_path = tmp_path / ".alex_cache.json"
        with patch("alex.utils.http.CACHE", cache_path), \
             patch("alex.utils.http.time.sleep") as sleep_mock:
            client = HttpClient()
            ok = self._resp(200, body={"ok": True})
            sequence = [self._resp(429, headers={"Retry-After": "38"}), ok]
            with patch.object(client.session, "get", side_effect=sequence):
                assert client.get_json("https://api.openalex.org/works") == {"ok": True}
            assert 38.0 in [c.args[0] for c in sleep_mock.call_args_list if c.args]


class TestOpenAlexApiKey:
    def test_api_key_sent_to_openalex_only(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENALEX_API_KEY", "sekret")
        cache_path = tmp_path / ".alex_cache.json"
        with patch("alex.utils.http.CACHE", cache_path), \
             patch("alex.utils.http.time.sleep"):
            client = HttpClient()
            ok = TestHttpClientRetry()._resp(200, body={"ok": True})
            with patch.object(client.session, "get", return_value=ok) as get_mock:
                client.get_json("https://api.openalex.org/works", params={"search": "x"})
                client.get_json("https://api.crossref.org/works", params={"query": "x"})
            oa_params = get_mock.call_args_list[0].kwargs["params"]
            cr_params = get_mock.call_args_list[1].kwargs["params"]
            assert oa_params == {"search": "x", "api_key": "sekret"}
            assert "api_key" not in cr_params

    def test_api_key_not_in_cache(self, tmp_path, monkeypatch):
        monkeypatch.setenv("OPENALEX_API_KEY", "sekret")
        cache_path = tmp_path / ".alex_cache.json"
        with patch("alex.utils.http.CACHE", cache_path), \
             patch("alex.utils.http.time.sleep"):
            client = HttpClient()
            ok = TestHttpClientRetry()._resp(200, body={"ok": True})
            with patch.object(client.session, "get", return_value=ok):
                client.get_json("https://api.openalex.org/works", params={"search": "x"})
            assert "sekret" not in cache_path.read_text()

    def test_no_key_means_no_param(self, tmp_path, monkeypatch):
        monkeypatch.delenv("OPENALEX_API_KEY", raising=False)
        cache_path = tmp_path / ".alex_cache.json"
        with patch("alex.utils.http.CACHE", cache_path), \
             patch("alex.utils.http.time.sleep"):
            client = HttpClient()
            ok = TestHttpClientRetry()._resp(200, body={"ok": True})
            with patch.object(client.session, "get", return_value=ok) as get_mock:
                client.get_json("https://api.openalex.org/works", params={"search": "x"})
            assert "api_key" not in get_mock.call_args.kwargs["params"]

from __future__ import annotations
import json
import logging
import os
import re
import threading
import time
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlsplit
import requests

logger = logging.getLogger(__name__)

CACHE = Path(__file__).resolve().parents[2] / ".alex_cache.json"

# Sentinel used by the cache helpers to distinguish "key absent" from
# "key cached as None" (the latter is purged on init but defensive code
# avoids ambiguity).
_CACHE_MISS = object()

# Retry only on transient failures: server-side errors and rate limits. 4xx
# responses other than 429 are deterministic — retrying them just wastes time
# and quota.
_RETRY_STATUS_CODES: frozenset[int] = frozenset({429, 500, 502, 503, 504})
# Three total attempts is the standard "first + two retries" pattern. Pair
# this with #1 (batched DOI lookups) and #2/#3 (gating dead connectors) so
# retries only fire against connectors that aren't permanently broken.
_DEFAULT_MAX_ATTEMPTS = 3
# Exponential backoff base (seconds): attempt 1 fails -> sleep 1s, attempt 2
# fails -> sleep 2s, attempt 3 fails -> give up. Honour `Retry-After` if the
# server sets it; otherwise use this schedule.
_BACKOFF_SCHEDULE = (1.0, 2.0, 4.0)
# Longest Retry-After we will sleep through. OpenAlex answers an exhausted
# daily budget with a Retry-After of hours; honouring that uncapped left
# every chain thread asleep until the 6h job ceiling killed the run
# (2026-06-22, 06-29, 07-20). Past the cap, the host is skipped for the
# rest of the Retry-After window and callers get None, same as any other
# failed request.
_MAX_RETRY_AFTER = 60.0

# Per-host auth params, read from the environment at request time. Added
# after the cache key is built so secrets never land in .alex_cache.json.
_HOST_AUTH_PARAMS: dict[str, tuple[str, str]] = {
    "api.openalex.org": ("api_key", "OPENALEX_API_KEY"),
}
# requests' HTTPError text embeds the full URL, auth params included. Actions
# masks secrets in CI logs; local runs need this.
_AUTH_PARAM_RE = re.compile(
    r"(\b(?:%s)=)[^&\s]+" % "|".join(re.escape(n) for n, _ in _HOST_AUTH_PARAMS.values())
)


def _redact(exc: Exception) -> str:
    return _AUTH_PARAM_RE.sub(r"\1***", str(exc))


class HttpClient:
    def __init__(self, mailto: str = "") -> None:
        self.session = requests.Session()
        ua = "AlexResearchLibrary/2.1.1"
        if mailto:
            ua += f" (mailto:{mailto})"
        self.session.headers.update({"User-Agent": ua, "Accept": "application/json"})
        # Discovery now fans out connector calls across threads, so cache
        # check-then-write and the JSON file write must be serialised. The
        # actual HTTP call happens outside the lock.
        self._cache_lock = threading.Lock()
        # host -> time.monotonic() deadline. Set when a server asks us to wait
        # longer than _MAX_RETRY_AFTER; requests to that host return None
        # until the deadline passes.
        self._blocked_until: dict[str, float] = {}
        if CACHE.exists():
            try:
                self.cache: dict[str, Any] = json.loads(CACHE.read_text(encoding="utf-8"))
            except Exception:
                self.cache = {}
        else:
            self.cache = {}
        # Purge legacy None entries from cache
        stale = [k for k, v in self.cache.items() if v is None]
        if stale:
            for k in stale:
                del self.cache[k]
            self._save_cache()
            logger.info("Purged %d stale None entries from cache", len(stale))

    def _save_cache(self) -> None:
        CACHE.write_text(json.dumps(self.cache, ensure_ascii=False, indent=2), encoding="utf-8")

    def _cache_get(self, key: str) -> Any:
        with self._cache_lock:
            return self.cache.get(key, _CACHE_MISS)

    def _cache_put(self, key: str, value: Any) -> None:
        with self._cache_lock:
            self.cache[key] = value
            self._save_cache()

    def _host_blocked(self, url: str) -> bool:
        host = urlsplit(url).hostname or ""
        until = self._blocked_until.get(host)
        if until is None:
            return False
        if time.monotonic() < until:
            return True
        self._blocked_until.pop(host, None)
        return False

    def _block_host(self, url: str, seconds: float) -> None:
        host = urlsplit(url).hostname or ""
        if host not in self._blocked_until:
            logger.warning("%s asked us to wait %.0fs (cap %.0fs); skipping it for "
                           "the rest of this window", host, seconds, _MAX_RETRY_AFTER)
        self._blocked_until[host] = time.monotonic() + seconds

    @staticmethod
    def _with_auth(url: str, params: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
        auth = _HOST_AUTH_PARAMS.get(urlsplit(url).hostname or "")
        value = os.getenv(auth[1], "") if auth else ""
        if not value:
            return params
        return {**(params or {}), auth[0]: value}

    def _request_with_retry(
        self,
        url: str,
        params: Optional[dict[str, Any]],
        headers: Optional[dict[str, str]],
        timeout: int,
        max_attempts: int = _DEFAULT_MAX_ATTEMPTS,
    ) -> requests.Response | None:
        """GET with retry on 429/5xx. Returns the final Response, or None on
        unrecoverable failure. Honours Retry-After when present."""
        last_exc: Exception | None = None
        params = self._with_auth(url, params)
        for attempt in range(1, max_attempts + 1):
            try:
                r = self.session.get(url, params=params, headers=headers, timeout=timeout)
            except requests.exceptions.RequestException as exc:
                last_exc = exc
                # Network-level failures (connection error, timeout) get the
                # same backoff treatment as 5xx — almost always transient.
                if attempt < max_attempts:
                    self._sleep_backoff(attempt, retry_after=None)
                    continue
                logger.warning("HTTP request failed for %s after %d attempts: %s",
                               url, attempt, _redact(exc))
                return None

            if r.status_code in _RETRY_STATUS_CODES and attempt < max_attempts:
                retry_after = self._parse_retry_after(r.headers.get("Retry-After"))
                if retry_after is not None and retry_after > _MAX_RETRY_AFTER:
                    self._block_host(url, retry_after)
                    return None
                logger.info("HTTP %d for %s — retrying (attempt %d/%d)",
                            r.status_code, url, attempt, max_attempts)
                self._sleep_backoff(attempt, retry_after=retry_after)
                continue

            return r

        # Loop exited without returning — all attempts exhausted on 429/5xx.
        if last_exc is not None:
            logger.warning("HTTP request failed for %s: %s", url, _redact(last_exc))
        return None

    @staticmethod
    def _sleep_backoff(attempt: int, retry_after: float | None) -> None:
        delay = retry_after if retry_after is not None else _BACKOFF_SCHEDULE[
            min(attempt - 1, len(_BACKOFF_SCHEDULE) - 1)
        ]
        time.sleep(delay)

    @staticmethod
    def _parse_retry_after(value: str | None) -> float | None:
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            # HTTP-date form (rfc1123). Fall back to backoff schedule rather
            # than parsing the date — rare in practice for the APIs we hit.
            return None

    def get_raw(
        self,
        url: str,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: int = 30,
    ) -> str | None:
        """HTTP GET returning raw response text. Cached, retried on 429/5xx,
        polite-delay between successive requests."""
        key = json.dumps({"url": url, "params": params or {}, "headers": headers or {}, "_raw": True}, sort_keys=True)
        cached = self._cache_get(key)
        if cached is not _CACHE_MISS:
            return cached
        if self._host_blocked(url):
            return None
        try:
            r = self._request_with_retry(url, params, headers, timeout)
            if r is None:
                return None
            try:
                r.raise_for_status()
            except requests.exceptions.RequestException as exc:
                logger.warning("HTTP request failed for %s: %s", url, _redact(exc))
                return None
            text = r.text
            self._cache_put(key, text)
            return text
        finally:
            time.sleep(0.5)

    def get_json(
        self,
        url: str,
        params: Optional[dict[str, Any]] = None,
        headers: Optional[dict[str, str]] = None,
        timeout: int = 30,
    ) -> Any:
        key = json.dumps({"url": url, "params": params or {}, "headers": headers or {}}, sort_keys=True)
        cached = self._cache_get(key)
        if cached is not _CACHE_MISS:
            return cached
        if self._host_blocked(url):
            return None
        try:
            r = self._request_with_retry(url, params, headers, timeout)
            if r is None:
                return None
            try:
                r.raise_for_status()
                data = r.json()
            except (requests.exceptions.RequestException, ValueError) as exc:
                logger.warning("HTTP request failed for %s: %s", url, _redact(exc))
                return None
            self._cache_put(key, data)
            return data
        finally:
            time.sleep(0.5)

from __future__ import annotations
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Optional
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
                               url, attempt, exc)
                return None

            if r.status_code in _RETRY_STATUS_CODES and attempt < max_attempts:
                retry_after = self._parse_retry_after(r.headers.get("Retry-After"))
                logger.info("HTTP %d for %s — retrying (attempt %d/%d)",
                            r.status_code, url, attempt, max_attempts)
                self._sleep_backoff(attempt, retry_after=retry_after)
                continue

            return r

        # Loop exited without returning — all attempts exhausted on 429/5xx.
        if last_exc is not None:
            logger.warning("HTTP request failed for %s: %s", url, last_exc)
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
        try:
            r = self._request_with_retry(url, params, headers, timeout)
            if r is None:
                return None
            try:
                r.raise_for_status()
            except requests.exceptions.RequestException as exc:
                logger.warning("HTTP request failed for %s: %s", url, exc)
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
        try:
            r = self._request_with_retry(url, params, headers, timeout)
            if r is None:
                return None
            try:
                r.raise_for_status()
                data = r.json()
            except (requests.exceptions.RequestException, ValueError) as exc:
                logger.warning("HTTP request failed for %s: %s", url, exc)
                return None
            self._cache_put(key, data)
            return data
        finally:
            time.sleep(0.5)

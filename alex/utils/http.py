from __future__ import annotations
import json
import fcntl
from email.utils import parsedate_to_datetime
from datetime import datetime, timezone
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
_OPENALEX_LOCK = threading.Lock()
_HOST_LOCKS_GUARD = threading.Lock()
_HOST_LOCKS: dict[str, threading.Lock] = {}


def _host_lock(url):
    host = urlsplit(url).hostname or ""
    with _HOST_LOCKS_GUARD:
        return _HOST_LOCKS.setdefault(host, threading.Lock())

_OPENALEX_POLICY_PATH = Path(__file__).resolve().parents[2] / 'config/openalex_request_policy.json'

def _openalex_policy():
    return json.loads(_OPENALEX_POLICY_PATH.read_text())


def _openalex_response_evidence(response):
    """Retain quota evidence without request URLs, keys, bodies or cookies."""
    retained, invalid = {}, []
    for name in ('Date', 'Retry-After', 'X-RateLimit-Limit',
                 'X-RateLimit-Remaining', 'X-RateLimit-Reset',
                 'X-RateLimit-Credits-Used'):
        value = response.headers.get(name)
        if value is None:
            continue
        valid = False
        if isinstance(value, str) and len(value) <= 128 and '\n' not in value and '\r' not in value:
            numeric = re.fullmatch(r'[0-9]+(?:\.[0-9]+)?', value.strip()) is not None
            if name != 'Date' and numeric:
                valid = True
            elif name in ('Date', 'Retry-After'):
                try:
                    parsed = parsedate_to_datetime(value)
                    valid = (parsed.tzinfo is not None and
                             parsed.strftime('%a, %d %b %Y %H:%M:%S GMT') == value and
                             parsed.utcoffset().total_seconds() == 0)
                except (TypeError, ValueError, OverflowError):
                    pass
        if valid:
            retained[name] = value
        else:
            invalid.append(name)
    return {'observed_at': datetime.fromtimestamp(time.time(), timezone.utc).isoformat(),
            'http_status': response.status_code, 'headers': retained,
            'invalid_header_names': invalid}


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
        self._openalex_hold = False
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

    def _openalex_request(self, url, params, headers, timeout):
        # Share pacing/backoff across threads, clients and CLI stages using
        # this checkout. Independent runners must obey the worker checkpoint.
        if self._openalex_hold:
            return None
        policy = _openalex_policy()
        if (policy.get('requests_enabled') is False or policy.get('owner_pause') is not None
                or policy.get('reconciliation_hold') is not None):
            self._openalex_hold = True
            logger.warning('OpenAlex requests paused pending provider-state reconciliation; no request sent')
            return None
        state_path = Path(os.getenv('ALEX_OPENALEX_STATE_PATH', str(CACHE.with_name(CACHE.name + '.openalex-policy'))))
        state_path.parent.mkdir(parents=True, exist_ok=True)
        with _OPENALEX_LOCK, state_path.with_suffix(state_path.suffix + '.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            try:
                state = json.loads(state_path.read_text()) if state_path.exists() else {}
            except (ValueError, OSError):
                logger.warning('OpenAlex pacing checkpoint unreadable; no request sent')
                return None
            # Count before sending, under the same lock and in the same durable
            # checkpoint as provider backoff. GitHub jobs in one pipeline run
            # share this file through pipeline-state, so later stages cannot
            # silently reset the owner's per-run ceiling.
            configured_limit = policy.get('max_openalex_requests_per_run', 250)
            if type(configured_limit) is not int or not 0 <= configured_limit <= 250:
                logger.warning('OpenAlex request budget invalid; no request sent')
                self._openalex_hold = True
                return None
            run_id = os.getenv('GITHUB_RUN_ID') or ('local-' + str(os.getpid()))
            if not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', run_id):
                logger.warning('OpenAlex run identity invalid; no request sent')
                self._openalex_hold = True
                return None
            attempts = state.get('request_attempts_by_run', {})
            if not isinstance(attempts, dict) or any(type(v) is not int or v < 0 for v in attempts.values()):
                logger.warning('OpenAlex request budget checkpoint invalid; no request sent')
                self._openalex_hold = True
                return None
            if attempts.get(run_id, 0) >= configured_limit:
                logger.info('OpenAlex per-run request budget exhausted; no request sent')
                self._openalex_hold = True
                return None
            now = time.time()
            hold = policy.get('retry_not_before')
            hold_until = datetime.fromisoformat(hold.replace('Z', '+00:00')).timestamp() if hold else 0
            if now < max(hold_until, state.get('retry_not_before', 0)):
                self._openalex_hold = True
                logger.info('OpenAlex remains in backoff; no request sent')
                return None
            delay = max(0, state.get('last_request_at', 0) + policy['min_interval_seconds'] - now)
            self._before_openalex_wait(delay, min(timeout, policy['request_timeout_seconds']))
            if delay:
                time.sleep(delay)
            state['last_request_at'] = time.time()
            attempts[run_id] = attempts.get(run_id, 0) + 1
            state['request_attempts_by_run'] = attempts
            def save():
                temp = state_path.with_suffix(state_path.suffix + '.tmp')
                temp.write_text(json.dumps(state))
                temp.replace(state_path)
            save()
            try:
                response = self._send_request(url, params=self._with_auth(url, params), headers=headers,
                                            timeout=min(timeout, policy['request_timeout_seconds']))
            except requests.exceptions.RequestException as exc:
                state['retry_not_before'] = time.time() + policy['failure_cooldown_seconds']
                self._openalex_hold = True
                state['last_failure'] = 'network_or_timeout'
                save()
                logger.warning('OpenAlex network/timeout failure; no automatic retry: %s', _redact(exc))
                return None
            state['last_response'] = _openalex_response_evidence(response)
            # Save even successful responses: remaining allowance and provider
            # reset evidence must survive the runner that received them.
            save()
            if response.status_code in (401, 403, 429) or response.status_code >= 500:
                retry_after = self._parse_retry_after(response.headers.get('Retry-After'))
                state['retry_not_before'] = time.time() + max(retry_after or 0, self._quota_reset_seconds(response), policy['failure_cooldown_seconds'])
                self._openalex_hold = True
                state['last_failure'] = 'HTTP' + str(response.status_code)
                state['last_failure_response'] = state['last_response']
                save()
                logger.warning('OpenAlex HTTP%d; provider paused, no automatic retry', response.status_code)
            reset = self._quota_reset_seconds(response)
            if reset:
                self._openalex_hold = True
                state['retry_not_before'] = max(state.get('retry_not_before', 0), time.time() + reset)
                state['last_failure'] = 'quota_exhausted'
                state['last_failure_response'] = state['last_response']
                save()
            return response

    def openalex_deferred(self) -> bool:
        return self._openalex_hold

    def on_openalex_deferred(self):
        pass

    def _before_openalex_wait(self, delay, timeout):
        pass

    def _send_request(self, url, **kwargs):
        return self.session.get(url, **kwargs)

    @staticmethod
    def _quota_reset_seconds(response):
        try:
            if float(response.headers.get('X-RateLimit-Remaining', '1')) <= 0:
                return max(1, float(response.headers.get('X-RateLimit-Reset') or 3600))
        except (ValueError, TypeError):
            pass
        return 0

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
        if urlsplit(url).hostname == 'api.openalex.org':
            return self._openalex_request(url, params, headers, timeout)
        # A delay in each worker does not serialize requests from other
        # workers. Share a lock across clients for the entire retry sequence
        # and final polite delay; independent hosts can still run in parallel.
        with _host_lock(url):
            if self._host_blocked(url):
                return None
            try:
                return self._request_other_host(url, params, headers, timeout, max_attempts)
            finally:
                time.sleep(0.5)

    def _request_other_host(self, url, params, headers, timeout, max_attempts):
        last_exc: Exception | None = None
        params = self._with_auth(url, params)
        for attempt in range(1, max_attempts + 1):
            try:
                r = self._send_request(url, params=params, headers=headers, timeout=timeout)
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
            from email.utils import parsedate_to_datetime
            try:
                date = parsedate_to_datetime(value)
                if date.tzinfo is None:
                    date = date.replace(tzinfo=timezone.utc)
                return max(0.0, date.timestamp() - time.time())
            except (ValueError, TypeError, OverflowError):
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
                logger.warning("HTTP request failed for %s: %s", url, _redact(exc))
                return None
            text = r.text
            self._cache_put(key, text)
            return text
        finally:
            if urlsplit(url).hostname == "api.openalex.org":
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
                logger.warning("HTTP request failed for %s: %s", url, _redact(exc))
                return None
            self._cache_put(key, data)
            return data
        finally:
            if urlsplit(url).hostname == "api.openalex.org":
                time.sleep(0.5)

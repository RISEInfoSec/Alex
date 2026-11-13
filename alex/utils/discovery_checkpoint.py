"""Bounded, replayable weekly discovery. No provider credentials in state."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import subprocess
import math
import xml.etree.ElementTree as ET
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from alex.utils.http import HttpClient, ProviderCoordinationRequired, _CACHE_MISS

logger = logging.getLogger(__name__)


class DiscoveryDeferred(RuntimeError):
    pass


class DiscoveryIncomplete(RuntimeError):
    """Nonzero exit after durable partial state, never a false green run."""


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False), encoding='utf-8')
    temp.replace(path)


class DiscoveryClient(HttpClient):
    def __init__(self, path: Path, window: dict, registry: dict, budgets: dict, mailto=''):
        super().__init__(mailto)
        self.cache.clear()  # The verified discovery checkpoint is the sole response cache.
        self.path = path
        self.guard = threading.RLock()
        self.local = threading.local()
        self.started = time.monotonic()
        self.last_sync = self.started
        self.sync_failed = False
        self.sync_enabled = os.getenv("ALEX_DISCOVERY_SYNC") == "1"
        self.runtime_seconds = budgets.get('runtime_seconds', 2700)
        self.deadline = self.started + self.runtime_seconds
        self.max_requests = budgets.get('max_requests', 300)
        self.max_openalex = budgets.get('openalex_max_requests', 20)
        self.requests = []
        self.openalex_count = 0
        self.blocked_sources = {}
        self.failures = {}
        self.cache_hits = 0
        self.replayed_tasks = 0
        # Corrupt state must fail, not silently start over.
        self.state = json.loads(path.read_text()) if path.exists() else {}
        if self.state.get('status') == 'complete' and self.state.get('window') != window:
            # Cover any gap since the last completed window, including backlogs.
            window['from_date'] = min(window['from_date'], self.state['window']['until_date'])
            self.state = {}
        if not self.state:
            self.state = {'schema_version': 1, 'window': window, 'registry': registry,
                          'responses': {}, 'tasks': {}, 'status': 'in_progress'}
        self.state['status'] = 'in_progress'
        self.state['orchestration_pass_id'] = os.getenv('ALEX_DISCOVERY_PASS_ID')
        self._save()

    def _cache_get(self, key):
        # HttpClient's legacy cache is not transported on pipeline-state. Using
        # it here would duplicate every durable response and rewrite a large,
        # pretty-printed file for every request. _read handles canonical replay.
        return _CACHE_MISS

    def _cache_put(self, key, value):
        pass

    def _save_cache(self):
        # Also suppress legacy-cache purging during HttpClient initialization.
        pass

    def _save(self):
        atomic_json(self.path, self.state)

    def sync(self, force=False):
        if self.sync_enabled and (force or time.monotonic() - self.last_sync >= 120):
            self._save()
            try:
                subprocess.run(['bash', 'scripts/state.sh', 'push', 'Checkpoint weekly discovery'],
                               check=True, timeout=120, cwd=self.path.parent.parent)
            except (subprocess.SubprocessError, OSError):
                self.sync_failed = True
                raise DiscoveryDeferred('state_sync_failed') from None
            self.last_sync = time.monotonic()

    def on_openalex_deferred(self):
        raise DiscoveryDeferred(self.openalex_deferred_reason())

    def _check_budget(self, url, wait=0, timeout=0):
        if self.sync_failed:
            raise DiscoveryDeferred('state_sync_failed')
        if time.monotonic() + wait + timeout >= self.deadline:
            raise DiscoveryDeferred('runtime_budget')
        if len(self.requests) >= self.max_requests:
            raise DiscoveryDeferred('request_budget')
        if urlsplit(url).hostname == 'api.openalex.org':
            if self._openalex_hold:
                raise DiscoveryDeferred(self.openalex_deferred_reason())
            if self.openalex_count >= self.max_openalex:
                raise DiscoveryDeferred('openalex_request_budget')

    def _before_openalex_wait(self, delay, timeout):
        with self.guard:
            self._check_budget('https://api.openalex.org/works', delay, timeout)

    def _send_request(self, url, **kwargs):
        host = urlsplit(url).hostname
        with self.guard:
            self._check_budget(url)
            if host == 'api.openalex.org':
                self.openalex_count += 1
            params = kwargs.get('params') or {}
            kind = ('singleton' if urlsplit(url).path.startswith('/works/') else
                    'search' if params.get('search') else 'list_filter')
            event = {'host': host, 'endpoint_type': kind,
                     'started_at': datetime.now(timezone.utc).isoformat(),
                     'http_status': None, 'elapsed_seconds': None, 'quota': {}}
            self.requests.append(event)
            kwargs['timeout'] = max(.1, min(kwargs.get('timeout', 30), self.deadline - time.monotonic()))
        start = time.monotonic()
        try:
            response = super()._send_request(url, **kwargs)
            self.local.last_status = response.status_code
            event['http_status'] = response.status_code
            for name in ('X-RateLimit-Limit', 'X-RateLimit-Remaining',
                         'X-RateLimit-Credits-Used', 'X-RateLimit-Reset'):
                value = response.headers.get(name)
                try:
                    if value is not None:
                        number = float(value)
                        if math.isfinite(number):
                            event['quota'][name] = number
                except (ValueError, TypeError):
                    pass
            retry = self._parse_retry_after(response.headers.get('Retry-After'))
            if retry is not None:
                event['quota']['retry_after_seconds'] = retry
            return response
        except Exception as exc:
            event['error_type'] = type(exc).__name__  # Never URLs or exception text.
            raise
        finally:
            event['elapsed_seconds'] = round(time.monotonic() - start, 3)
            with self.guard:
                # Survives interruption before a task/receipt is completed.
                self.state['last_attempt_requests'] = self.requests
                self._save()

    def _read(self, method, url, params=None, headers=None, timeout=30):
        # Persist only a hash of request parameters; don't serialize auth headers.
        safe_params = {k: v for k, v in (params or {}).items() if k.lower() not in ('api_key', 'token')}
        key = hashlib.sha256(json.dumps([method, url, safe_params], sort_keys=True).encode()).hexdigest()
        with self.guard:
            if key in self.state['responses']:
                self.cache_hits += 1
                return self.state['responses'][key]
        self.local.last_status = None
        with self.guard:
            self._check_budget(url)
        value = getattr(super(), method)(url, params=params, headers=headers, timeout=timeout)
        status = self.local.last_status
        if value is None and status != 404:
            held_openalex = urlsplit(url).hostname == 'api.openalex.org' and self.openalex_deferred()
            reason = self.openalex_deferred_reason() if held_openalex else 'request_failed'
            if held_openalex:
                self.blocked_sources['OpenAlex'] = reason
            with self.guard:
                self.sync()
            raise DiscoveryDeferred(reason)
        if method == 'get_raw' and urlsplit(url).hostname == 'export.arxiv.org' and value is not None:
            try:
                ET.fromstring(value)
            except ET.ParseError:
                raise DiscoveryDeferred('invalid_xml_response') from None
        with self.guard:
            self.state['responses'][key] = value
            self._save()
            self.sync()
        return value

    def get_json(self, url, params=None, headers=None, timeout=30):
        return self._read('get_json', url, params, headers, timeout)

    def get_raw(self, url, params=None, headers=None, timeout=30):
        return self._read('get_raw', url, params, headers, timeout)

    def run_task(self, name, fn):
        with self.guard:
            if name in self.state['tasks']:
                self.replayed_tasks += 1
                return self.state['tasks'][name]
        source = name.split(':', 1)[0]
        try:
            if source == 'OpenAlex' and self.openalex_deferred():
                raise DiscoveryDeferred(self.openalex_deferred_reason())
            if source in self.blocked_sources:
                raise DiscoveryDeferred(self.blocked_sources[source])
            if time.monotonic() >= self.deadline:
                raise DiscoveryDeferred('runtime_budget')
            result = fn()
            with self.guard:
                self.state['tasks'][name] = result
                self.failures.pop(name, None)
                self._save()
            return result
        except Exception as exc:
            if isinstance(exc, ProviderCoordinationRequired):
                self.blocked_sources['OpenAlex'] = 'openalex_shared_coordinator_required'
            if isinstance(exc, DiscoveryDeferred) and str(exc) in (
                    'openalex_request_budget', 'openalex_run_request_budget', 'openalex_cooldown'):
                self.blocked_sources['OpenAlex'] = str(exc)
            with self.guard:
                self.failures[name] = ('openalex_shared_coordinator_required' if isinstance(exc, ProviderCoordinationRequired)
                                       else str(exc) if isinstance(exc, DiscoveryDeferred) else type(exc).__name__)
            logger.warning('Discovery task deferred: %s (%s)', name, self.failures[name])
            return []

    def finish(self, receipt_path, new_candidates):
        with self.guard:
            done = len(self.state['tasks'])
            status = ('partial' if done else 'deferred') if self.failures else 'complete'
            if self.failures and all(v not in ('runtime_budget', 'request_budget',
                    'openalex_request_budget', 'openalex_run_request_budget', 'openalex_cooldown',
                    'openalex_shared_coordinator_required')
                    for v in self.failures.values()) and not done:
                status = 'failed'
            self.state['status'] = status
            self.state['deferred_tasks'] = self.failures
            self._save()
            receipt = {'schema_version': 1, 'status': status, 'window': self.state['window'],
                       'orchestration_pass_id': self.state['orchestration_pass_id'],
                       'responses_cached': len(self.state['responses']),
                       'completed_at': datetime.now(timezone.utc).isoformat(),
                       'elapsed_seconds': round(time.monotonic() - self.started, 3),
                       'completed_tasks': done, 'replayed_tasks': self.replayed_tasks,
                       'deferred_tasks': self.failures, 'new_candidates': new_candidates,
                       'actual_request_count': len(self.requests), 'openalex_request_count': self.openalex_count,
                       'checkpoint_cache_hits': self.cache_hits, 'requests': self.requests,
                       'budgets': {'runtime_seconds': self.runtime_seconds,
                                   'max_requests': self.max_requests, 'openalex_max_requests': self.max_openalex}}
            atomic_json(receipt_path, receipt)
            self.sync(force=True)
        if status != 'complete':
            raise DiscoveryIncomplete(f'Discovery {status}; progress saved; see {receipt_path}')
        return receipt

"""Input-bound harvest responses, retained without rewriting the full cache per call."""
from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import threading
import time

from alex.utils.http import HttpClient, _CACHE_MISS


class HarvestCheckpointError(RuntimeError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class HarvestClient(HttpClient):
    def __init__(self, path, input_sha256, mailto='', *, publish=None):
        super().__init__(mailto)
        self.cache.clear()  # Never use the untransported legacy cache.
        self.path = Path(path)
        self.guard = threading.RLock()
        self.request_locks = {}
        self.local = threading.local()
        self.failed = False
        self.last_sync = time.monotonic()
        self.publish = publish or self._publish
        self.cache_hits = 0
        self.responses_added = 0
        self.not_found_added = 0
        complete = False
        header = None
        if self.path.exists():
            try:
                with self.path.open(encoding='utf-8') as stream:
                    first = next(stream)
                    header = json.loads(first)
                    if (not first.endswith('\n') or header.get('schema_version') != 1
                            or not re.fullmatch('[0-9a-f]{64}', str(header.get('input_sha256', '')))):
                        raise ValueError('Invalid header')
                    for line in stream:
                        if not line.endswith('\n'):
                            raise ValueError('Incomplete checkpoint line')
                        record = json.loads(line)
                        if record.get('event') == 'response':
                            payload = {'request_sha256':record['request_sha256'], 'response':record['response']}
                            if digest(payload) != record['sha256'] or record['response'] is None:
                                raise ValueError('Invalid response digest')
                            self.cache[record['request_sha256']] = record['response']
                            complete = False
                        elif record.get('event') == 'not_found':
                            payload = {k:record[k] for k in ('request_sha256','http_status','evidence')}
                            if record['http_status'] != 404 or digest(payload) != record['sha256']:
                                raise ValueError('Invalid not-found outcome')
                            self.cache[record['request_sha256']] = None
                            complete = False
                        elif record.get('event') in ('begin', 'complete'):
                            complete = record['event'] == 'complete'
                        else:
                            raise ValueError('Unknown checkpoint record')
            except (ValueError, KeyError, TypeError, AttributeError, StopIteration, OSError):
                raise HarvestCheckpointError('Invalid harvest checkpoint; reconcile before requests') from None
        if header and header['input_sha256'] != input_sha256:
            if not complete:
                raise HarvestCheckpointError('Unfinished harvest belongs to another input; reconcile before requests')
            # Retain the prior completed input, matching the state branch's bounded rollback model.
            previous = self.path.with_name('harvest_response_cache_previous.jsonl')
            temp = previous.with_suffix('.tmp')
            shutil.copyfile(self.path, temp)
            temp.replace(previous)
            self.cache.clear()
            header = None
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if header is None:
            temp = self.path.with_suffix('.tmp')
            temp.write_text(json.dumps({'schema_version':1, 'input_sha256':input_sha256})+'\n', encoding='utf-8')
            temp.replace(self.path)
        self._append({'event':'begin'})
        self.sync(force=True)  # Verify state access before any source work.

    def _save_cache(self):
        pass

    def _append(self, record):
        try:
            with self.path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(record, ensure_ascii=False, separators=(',', ':'))+'\n')
                stream.flush()
                os.fsync(stream.fileno())
        except OSError:
            self.failed = True
            raise HarvestCheckpointError('Harvest checkpoint write failed') from None

    def _publish(self):
        if os.getenv('ALEX_DISCOVERY_SYNC') == '1' or os.getenv('ALEX_HARVEST_SYNC') == '1':
            subprocess.run(['bash','scripts/state.sh','push','Preserve harvest responses'],
                           cwd=self.path.parent.parent, check=True, timeout=120)

    def sync(self, force=False):
        with self.guard:
            if self.failed:
                raise HarvestCheckpointError('Harvest checkpoint failed; no further requests')
            if force or time.monotonic()-self.last_sync >= 120:
                try:
                    self.publish()
                except Exception:
                    self.failed = True
                    raise HarvestCheckpointError('Harvest checkpoint sync failed; no further requests') from None
                self.last_sync = time.monotonic()
                print(f'Harvest checkpoint: {len(self.cache)} retained outcomes; '
                      f'{self.responses_added} new responses; {self.not_found_added} new not-found outcomes; '
                      f'{self.cache_hits} cache hits', flush=True)

    def _cache_get(self, key):
        with self.guard:
            if self.failed:
                raise HarvestCheckpointError('Harvest checkpoint failed; no further requests')
            value = self.cache.get(digest(key), _CACHE_MISS)
            if value is not _CACHE_MISS:
                self.cache_hits += 1
            return value

    def _cache_put(self, key, value):
        if value is None:
            return  # A JSON null is not a reusable successful metadata response.
        with self.guard:
            # Hash request keys so caller-provided authentication headers cannot enter state.
            key = digest(key)
            payload = {'request_sha256':key, 'response':value}
            self._append({'event':'response', **payload, 'sha256':digest(payload)})
            self.cache[key] = value
            self.responses_added += 1
            if not self.failed:
                self.sync()

    def get_json(self, url, params=None, headers=None, timeout=30):
        key = digest({'url':url, 'params':params or {}, 'headers':headers or {}})
        with self.guard:
            lock = self.request_locks.setdefault(key, threading.Lock())
        with lock:
            self.local.json_key = json.dumps({'url':url, 'params':params or {}, 'headers':headers or {}}, sort_keys=True)
            try:
                return super().get_json(url, params, headers, timeout)
            finally:
                del self.local.json_key

    def _cache_not_found(self, key, evidence=None):
        """Retain an observed HTTP404, never manufacture an empty response body."""
        with self.guard:
            key = digest(key)
            payload = {'request_sha256':key, 'http_status':404,
                       'evidence':evidence or {'source':'http_response', 'run_id':os.getenv('GITHUB_RUN_ID')}}
            self._append({'event':'not_found', **payload, 'sha256':digest(payload)})
            self.cache[key] = None
            self.not_found_added += 1
            if not self.failed:
                self.sync()

    def _request_with_retry(self, *args, **kwargs):
        response = super()._request_with_retry(*args, **kwargs)
        key = getattr(self.local, 'json_key', None)
        if response is not None and response.status_code == 404 and key is not None:
            self._cache_not_found(key)
        return response

    def _send_request(self, url, **kwargs):
        with self.guard:
            if self.failed:
                raise HarvestCheckpointError('Harvest checkpoint failed; no further requests')
        return super()._send_request(url, **kwargs)

    def finish(self, complete=False):
        # Called after all worker threads have terminated and output has been saved.
        with self.guard:
            if complete and not self.failed:
                self._append({'event':'complete'})
            self.sync(force=True)

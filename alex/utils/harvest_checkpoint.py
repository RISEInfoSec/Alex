"""Input-bound harvest responses, retained without rewriting the full cache per call."""
from __future__ import annotations

import hashlib
import json
import os
import re
import signal
from pathlib import Path
import shutil
import subprocess
import threading
import time
from urllib.parse import urlsplit

from alex.utils.http import HttpClient, _CACHE_MISS


class HarvestCheckpointError(RuntimeError):
    pass


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def file_sha256(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def verified_completed_output(output_path, completed_sha, input_sha):
    if not output_path or not Path(output_path).is_file():
        return False
    output_path = Path(output_path)
    current = file_sha256(output_path)
    if current == completed_sha:
        return True
    # Rescore legitimately changes the output. Its main-branch lineage file
    # must bind both hashes and the exact prior harvest input.
    lineage_path = output_path.with_name('.harvest_output_lineage.json')
    try:
        lineage = json.loads(lineage_path.read_text(encoding='utf-8'))
        return (lineage.get('schema_version') == 1
                and lineage.get('harvest_input_sha256') == input_sha
                and lineage.get('harvest_output_sha256') == completed_sha
                and lineage.get('rescore_output_sha256') == current)
    except (OSError, ValueError, TypeError, AttributeError):
        return False


class HarvestClient(HttpClient):
    def __init__(self, path, input_sha256, mailto='', *, publish=None, output_path=None):
        super().__init__(mailto)
        self.cache.clear()  # Never use the untransported legacy cache.
        self.path = Path(path)
        self.output_path = Path(output_path) if output_path is not None else None
        self.uncertain_path = self.path.with_name(self.path.name + '.uncertain')
        if self.uncertain_path.exists():
            raise HarvestCheckpointError('Harvest state uncertain; reconcile before requests')
        self._guard_owned = False
        self.guard = threading.RLock()
        self.request_locks = {}
        self.local = threading.local()
        self.failed = False
        self.stop_sends = threading.Event()
        self.admitted_requests = 0
        self.last_sync = time.monotonic()
        self.publish = publish or self._publish
        self.cache_hits = 0
        self.responses_added = 0
        self.not_found_added = 0
        complete = False
        completed_output_sha256 = None
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
                            completed_output_sha256 = record.get('output_sha256') if complete else None
                            if complete and digest({'event':'complete', 'output_sha256':completed_output_sha256}) != record.get('sha256'):
                                raise ValueError('Invalid completion digest')
                        else:
                            raise ValueError('Unknown checkpoint record')
            except (ValueError, KeyError, TypeError, AttributeError, StopIteration, OSError):
                raise HarvestCheckpointError('Invalid harvest checkpoint; reconcile before requests') from None
        if header and not complete:
            # A prior attempt may have sent requests before its last state
            # push became uncertain. Never replay or send from that state
            # without an explicit reconciliation procedure.
            raise HarvestCheckpointError('Unfinished harvest checkpoint; reconcile before requests')
        if complete:
            if (not re.fullmatch('[0-9a-f]{64}', str(completed_output_sha256 or ''))
                    or not verified_completed_output(self.output_path, completed_output_sha256,
                                                     header.get('input_sha256'))):
                raise HarvestCheckpointError('Completed harvest output unverified; reconcile before requests')
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
            if not self._guard_owned:
                try:
                    self._write_guard({'phase':'local_append_failure'})
                except HarvestCheckpointError:
                    pass
            raise HarvestCheckpointError('Harvest checkpoint write failed') from None

    def _write_guard(self, payload):
        try:
            with self.uncertain_path.open('x', encoding='utf-8') as marker:
                marker.write(json.dumps(payload) + '\n')
                marker.flush()
                os.fsync(marker.fileno())
            self._guard_owned = True
        except OSError:
            self.failed = True
            raise HarvestCheckpointError('Cannot retain harvest sync guard') from None

    def _clear_guard(self):
        try:
            self.uncertain_path.unlink()
            self._guard_owned = False
        except OSError:
            self.failed = True
            raise HarvestCheckpointError('Harvest sync guard could not be cleared') from None

    def _publish(self):
        if os.getenv('ALEX_DISCOVERY_SYNC') == '1' or os.getenv('ALEX_HARVEST_SYNC') == '1':
            proc = subprocess.Popen(['bash','scripts/state.sh','push','Preserve harvest responses'],
                                    cwd=self.path.parent.parent, start_new_session=True)
            try:
                code = proc.wait(timeout=120)
            except subprocess.TimeoutExpired:
                # A timeout is an ambiguous remote write, even if the process
                # group is terminated. Never repeat it automatically.
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    raise HarvestCheckpointError('State sync cleanup unconfirmed; reconcile') from None
                raise HarvestCheckpointError('State sync timed out; remote outcome and descendant cleanup unconfirmed') from None
            if code:
                raise HarvestCheckpointError('State sync failed; reconcile before retry')

    def sync(self, force=False):
        with self.guard:
            if self.failed:
                raise HarvestCheckpointError('Harvest checkpoint failed; no further requests')
            if force or time.monotonic()-self.last_sync >= 120:
                own_guard = not self._guard_owned
                if own_guard:
                    self._write_guard({'phase':'state_sync'})
                try:
                    self.publish()
                except HarvestCheckpointError as exc:
                    self.failed = True
                    raise HarvestCheckpointError(str(exc)) from None
                except Exception:
                    self.failed = True
                    raise HarvestCheckpointError('Harvest checkpoint sync failed; reconcile before retry') from None
                if own_guard:
                    self._clear_guard()
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

    @staticmethod
    def _valid_response(url, value):
        if not isinstance(value, dict):
            return False
        parsed = urlsplit(url)
        if parsed.hostname == 'api.crossref.org' and parsed.path.startswith('/works/'):
            return isinstance(value.get('message'), dict)
        if parsed.hostname == 'api.openalex.org' and parsed.path.rstrip('/') == '/works':
            return isinstance(value.get('results'), list)
        if parsed.hostname == 'api.semanticscholar.org' and parsed.path == '/graph/v1/paper/search':
            return isinstance(value.get('data'), list)
        return False

    def _cache_put(self, key, value):
        url = getattr(self.local, 'json_url', None)
        if value is not None and url is not None and not self._valid_response(url, value):
            self.stop()
            raise HarvestCheckpointError('Provider response invalid; harvest held')
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
            self.local.json_url = url
            try:
                value = super().get_json(url, params, headers, timeout)
                if value is not None:
                    if not self._valid_response(url, value):
                        self.stop()
                        raise HarvestCheckpointError('Provider response invalid; harvest held')
                    return value
                # Only a retained, exact Crossref DOI 404 is an ordinary
                # missing result. Holds, denials, bad JSON and JSON null do
                # not establish that a lookup completed successfully.
                parsed = urlsplit(url)
                is_doi_lookup = (parsed.hostname == 'api.crossref.org'
                                 and parsed.path.startswith('/works/')
                                 and len(parsed.path) > len('/works/'))
                with self.guard:
                    retained = self.cache.get(digest(self.local.json_key), _CACHE_MISS)
                if is_doi_lookup and retained is None:
                    return None
                self.stop()
                raise HarvestCheckpointError('Provider lookup incomplete; harvest held')
            finally:
                del self.local.json_key
                del self.local.json_url

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

    def stop(self):
        with self.guard:
            self.stop_sends.set()

    def check_active(self):
        with self.guard:
            if self.failed or self.stop_sends.is_set():
                raise HarvestCheckpointError('Harvest stopped; no further requests')

    def _send_request(self, url, **kwargs):
        # Admission and stop use the same lock. Calls admitted before stop
        # may still finish; callers wait for them and retain their outcomes.
        with self.guard:
            self.check_active()
            self.admitted_requests += 1
        try:
            return super()._send_request(url, **kwargs)
        finally:
            with self.guard:
                self.admitted_requests -= 1

    def finish(self, complete=False, *, output_sha256=None, staged_name=None, backup_name=None):
        # The uncertain marker is local evidence and remains until output
        # promotion succeeds. A failed push must never be retried blindly.
        with self.guard:
            if complete:
                if self.failed or self.stop_sends.is_set():
                    raise HarvestCheckpointError('Harvest stopped; completion refused')
                if self.output_path is None or not re.fullmatch('[0-9a-f]{64}', str(output_sha256 or '')):
                    raise HarvestCheckpointError('Harvest output digest required for completion')
                self._write_guard({'phase':'completion', 'output_sha256':output_sha256,
                                   'staged_name':staged_name, 'backup_name':backup_name})
                payload = {'event':'complete', 'output_sha256':output_sha256}
                self._append({**payload, 'sha256':digest(payload)})
            self.sync(force=True)

    def confirm_output(self):
        if self.output_path is None or not self.uncertain_path.is_file():
            raise HarvestCheckpointError('Harvest completion guard missing')
        try:
            expected = json.loads(self.uncertain_path.read_text())['output_sha256']
            if not self.output_path.is_file() or file_sha256(self.output_path) != expected:
                raise HarvestCheckpointError('Harvest output does not match completion guard')
            self._clear_guard()
        except (OSError, ValueError, KeyError, TypeError):
            raise HarvestCheckpointError('Harvest completion guard could not be verified') from None

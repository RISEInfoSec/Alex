"""Retain exact paid responses; ambiguous sends never become automatic retries."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import time
import uuid
from datetime import datetime, timezone
from alex.utils.discovery_checkpoint import atomic_json


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


class PaidRequestHeld(RuntimeError):
    pass


class Ledger:
    def __init__(self, root, keys, *, publish=None, identity=None, validate=None):
        self.root = Path(root)
        self.path = self.root / 'data/classification_request_ledger.json'
        self.state = json.loads(self.path.read_text()) if self.path.exists() else {
            'schema_version': 1, 'entries': {}, 'invocations': {}}
        if self.state.get('schema_version') != 1 or not isinstance(self.state.get('entries'), dict):
            raise PaidRequestHeld('Invalid paid request ledger')
        self.keys = set(keys)
        self.identity = identity or (os.getenv('GITHUB_RUN_ID', 'local-' + uuid.uuid4().hex)
                                      + ':' + os.getenv('GITHUB_RUN_ATTEMPT', '1') + ':' + uuid.uuid4().hex)
        if self.identity in self.state['invocations']:
            raise PaidRequestHeld('Paid invocation identity already recorded')
        self.condition = threading.Condition(threading.RLock())
        self.failed = self.sync_failed = False
        self.last_sync = time.monotonic()
        self.publish = publish or self._publish
        entries = self.state['entries']
        for key in self.keys:
            entry = entries.get(key)
            if entry and entry['status'] not in ('complete', 'not_sent'):
                raise PaidRequestHeld('Prior paid outcome requires reconciliation: ' + key)
            if entry and entry['status'] == 'complete' and digest(entry['response']) != entry['response_sha256']:
                raise PaidRequestHeld('Paid response digest mismatch')
            if entry and entry['status'] == 'complete' and validate is not None:
                validate(entry['response'])
        for invocation in self.state['invocations'].values():
            if invocation['status'] == 'running':
                unknown = self.keys.intersection(invocation['request_keys'])
                if any(entries.get(k, {}).get('status') not in ('complete', 'not_sent') for k in unknown):
                    raise PaidRequestHeld('Interrupted paid invocation requires reconciliation')
        for key in self.keys:
            if entries.get(key, {}).get('status') == 'not_sent':
                del entries[key]  # A new reservation no longer proves a new send did not occur.
        self.state['invocations'][self.identity] = {
            'status': 'running', 'request_keys': sorted(self.keys),
            'started_at': datetime.now(timezone.utc).isoformat()}
        self.save(force=True)  # Reserve the whole work set remotely before any send.

    def complete(self, body):
        with self.condition:
            return self.state['entries'].get(digest(body), {}).get('status') == 'complete'

    def _publish(self):
        if os.getenv('ALEX_DISCOVERY_SYNC') == '1' or os.getenv('ALEX_CLASSIFICATION_SYNC') == '1':
            subprocess.run(['bash', 'scripts/state.sh', 'push', 'Preserve paid classification evidence'],
                           cwd=self.root, check=True, timeout=120)

    def save(self, force=False):
        atomic_json(self.path, self.state)
        if not self.sync_failed and (force or time.monotonic() - self.last_sync >= 120):
            try:
                self.publish()
            except Exception:
                self.failed = self.sync_failed = True
                raise PaidRequestHeld('Paid evidence state sync failed') from None
            self.last_sync = time.monotonic()

    def perform(self, body, send, validate):
        key = digest(body)
        with self.condition:
            if key not in self.keys:
                raise PaidRequestHeld('Unreserved paid request')
            entry = self.state['entries'].get(key, {})
            while (entry.get('status') in ('started', 'response_received')
                   and entry.get('invocation') == self.identity and not self.failed):
                self.condition.wait()
                entry = self.state['entries'].get(key, {})
            if entry.get('status') == 'complete':
                if digest(entry['response']) != entry['response_sha256']:
                    raise PaidRequestHeld('Paid response digest mismatch')
                return validate(entry['response'])
            if self.failed or entry.get('status') not in (None, 'not_sent'):
                raise PaidRequestHeld('Paid processing stopped; reconcile failed request')
            entry = {'status': 'started', 'invocation': self.identity,
                     'request_sha256': key, 'started_at': datetime.now(timezone.utc).isoformat()}
            self.state['entries'][key] = entry
            self.save()
        try:
            response = send()
            with self.condition:
                entry.update(response=response, response_sha256=digest(response),
                             status='response_received')
                self.save()
            result = validate(response)
            with self.condition:
                entry.update(status='complete', completed_at=datetime.now(timezone.utc).isoformat())
                self.save()
            return result
        except Exception as exc:
            with self.condition:
                self.failed = True
                entry.update(status='held', error_type=type(exc).__name__)
                self.save()
            raise
        finally:
            with self.condition:
                self.condition.notify_all()

    def finish(self, failed=False):
        # Called only after all in-flight threads terminate. An absent entry
        # can now be proven not sent; a killed runner cannot make that claim.
        with self.condition:
            for key in self.keys:
                self.state['entries'].setdefault(key, {'status': 'not_sent', 'invocation': self.identity})
            self.state['invocations'][self.identity].update(
                status='blocked' if failed or self.failed else 'requests_finished',
                completed_at=datetime.now(timezone.utc).isoformat())
            self.save(force=True)

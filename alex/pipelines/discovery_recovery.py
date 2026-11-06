"""Finite discovery continuation inside one GitHub job and concurrency lease."""
from __future__ import annotations

import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone

from alex.utils.discovery_checkpoint import atomic_json


class RecoveryStop(RuntimeError):
    pass


def read_json(path, default=None):
    return json.loads(path.read_text()) if path.exists() else default


def bounded_integer(value, upper):
    if type(value) is not int or not 0 < value <= upper:
        raise ValueError('Invalid recovery bound')
    return value


class Recovery:
    def __init__(self, root, *, invoke=None, publish=None, clock=time.time,
                 monotonic=time.monotonic, sleep=time.sleep, run_id=None):
        self.root = Path(root)
        self.data = self.root / 'data'
        self.clock, self.monotonic, self.sleep = clock, monotonic, sleep
        self.invoke = invoke or self._invoke
        self.publish = publish or self._publish
        policy = read_json(self.root / 'config/weekly_recovery_policy.json')
        self.max_passes = bounded_integer(policy['max_passes'], 6)
        self.max_seconds = bounded_integer(policy['max_runtime_seconds'], 14400)
        self.max_wait = bounded_integer(policy['max_cooldown_wait_seconds'], 3600)
        self.max_resumptions = bounded_integer(policy['max_cooldown_resumptions'], 1)
        budgets = read_json(self.root / 'config/weekly_discovery_policy.json')
        self.pass_seconds = bounded_integer(budgets['runtime_seconds'], 2700)
        self.requests_limit = bounded_integer(budgets['max_requests'], 300)
        self.openalex_limit = bounded_integer(budgets['openalex_max_requests'], 250)
        self.started = monotonic()
        self.waited = 0
        self.resumptions = 0
        self.sync_failed = False
        self.path = self.data / 'discovery_recovery_receipt.json'
        self.history_path = self.data / 'discovery_recovery_ledger.json'
        self.history = read_json(self.history_path, {'schema_version': 1, 'runs': []})
        if self.history.get('schema_version') != 1 or not isinstance(self.history.get('runs'), list):
            raise ValueError('Invalid recovery ledger')
        identity = run_id or (os.environ.get('GITHUB_RUN_ID', 'local-' + uuid.uuid4().hex)
                              + ':' + os.environ.get('GITHUB_RUN_ATTEMPT', '1'))
        if any(r['run_id'] == identity for r in self.history['runs']):
            raise ValueError('Recovery invocation already recorded; reconcile before replay')
        self.record = {'schema_version': 1, 'run_id': identity, 'status': 'running',
                       'started_at': self.timestamp(), 'passes': [],
                       'limits': {'max_passes': self.max_passes,
                                  'max_runtime_seconds': self.max_seconds,
                                  'max_cooldown_wait_seconds': self.max_wait,
                                  'max_cooldown_resumptions': self.max_resumptions}}

    def timestamp(self):
        return datetime.fromtimestamp(self.clock(), timezone.utc).isoformat()

    def remaining(self):
        return self.max_seconds - (self.monotonic() - self.started)

    def save(self, *, remote=True):
        self.record['updated_at'] = self.timestamp()
        self.record['elapsed_seconds'] = round(self.monotonic() - self.started, 3)
        summary = {k: v for k, v in self.record.items() if k != 'passes'}
        summary['passes'] = [{k: v for k, v in p.items() if k != 'receipt'}
                             for p in self.record['passes']]
        self.history['runs'] = [r for r in self.history['runs']
                                if r['run_id'] != self.record['run_id']] + [summary]
        atomic_json(self.path, self.record)
        atomic_json(self.history_path, self.history)
        if remote:
            try:
                self.publish()
            except Exception:
                self.sync_failed = True
                raise RecoveryStop('state_sync_failed') from None

    def _publish(self):
        subprocess.run(['bash', 'scripts/state.sh', 'push', 'Checkpoint discovery recovery'],
                       cwd=self.root, check=True, timeout=120)

    def _invoke(self, pass_id, runtime):
        env = {**os.environ, 'ALEX_DISCOVERY_PASS_ID': pass_id,
               'ALEX_DISCOVERY_RUNTIME_LIMIT': str(runtime)}
        with subprocess.Popen([sys.executable, '-m', 'alex.cli', 'discover'],
                              cwd=self.root, env=env, start_new_session=True) as process:
            try:
                return process.wait(timeout=runtime + 150)
            except subprocess.TimeoutExpired:
                # Kill the whole child group, including any state push, before
                # returning. Never overlap an orphaned child with another pass.
                os.killpg(process.pid, signal.SIGTERM)
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                raise RecoveryStop('child_timeout') from None

    def hold(self):
        state = read_json(self.data / 'discovery_openalex_state.json', {})
        deadline = state.get('retry_not_before', 0)
        if isinstance(deadline, bool) or not isinstance(deadline, (float, int)) or not math.isfinite(deadline) or deadline < 0:
            raise RecoveryStop('invalid_provider_state')
        policy = read_json(self.root / 'config/openalex_request_policy.json')
        configured = policy.get('retry_not_before')
        if configured:
            parsed = datetime.fromisoformat(configured.replace('Z', '+00:00'))
            if parsed.tzinfo is None:
                raise RecoveryStop('invalid_provider_policy')
            deadline = max(deadline, parsed.timestamp())
        return deadline, state.get('last_failure')

    def wait_for_hold(self):
        deadline, failure = self.hold()
        if failure in ('HTTP401', 'HTTP403', 'quota_exhausted'):
            raise RecoveryStop('provider_access_or_quota_requires_review')
        if deadline <= self.clock():
            return
        self.record['retry_not_before'] = datetime.fromtimestamp(deadline, timezone.utc).isoformat()
        if self.resumptions >= self.max_resumptions:
            raise RecoveryStop('cooldown_resumption_limit')
        if deadline - self.clock() > min(self.max_wait - self.waited, self.remaining() - 240):
            raise RecoveryStop('cooldown_exceeds_run_budget')
        self.resumptions += 1
        self.record['status'] = 'waiting_provider_cooldown'
        self.save()
        while deadline > self.clock():
            delay = min(60, deadline - self.clock())
            if delay > min(self.max_wait - self.waited, self.remaining() - 240):
                raise RecoveryStop('cooldown_exceeds_run_budget')
            print('Recovery waiting for persisted provider cooldown', flush=True)
            self.sleep(delay)
            self.waited += delay
            deadline, failure = self.hold()
            if failure in ('HTTP401', 'HTTP403', 'quota_exhausted'):
                raise RecoveryStop('provider_access_or_quota_requires_review')
        self.record['status'] = 'running'
        self.record['cooldown_resumptions'] = self.resumptions
        self.record['cooldown_wait_seconds'] = self.waited
        self.save()

    def verify(self, entry, code, runtime):
        if code not in (0, 1):
            raise RecoveryStop('child_interrupted_or_invalid_exit')
        path = self.data / 'discovery_run_receipt.json'
        raw = path.read_bytes()
        receipt = json.loads(raw)
        state = read_json(self.data / 'discovery_checkpoint.json')
        if (receipt.get('orchestration_pass_id') != entry['pass_id']
                or state.get('orchestration_pass_id') != entry['pass_id']
                or receipt.get('window') != state.get('window')
                or receipt.get('status') != state.get('status')
                or receipt.get('responses_cached') != len(state['responses'])
                or receipt.get('completed_tasks') != len(state['tasks'])):
            raise RecoveryStop('receipt_checkpoint_mismatch')
        requests = receipt['requests']
        count = receipt['actual_request_count']
        oa = receipt['openalex_request_count']
        if (type(count) is not int or count != len(requests) or count > self.requests_limit
                or type(oa) is not int or oa != sum(r['host'] == 'api.openalex.org' for r in requests)
                or oa > self.openalex_limit or receipt['budgets']['runtime_seconds'] > runtime
                or receipt['budgets']['max_requests'] > self.requests_limit
                or receipt['budgets']['openalex_max_requests'] > self.openalex_limit):
            raise RecoveryStop('receipt_budget_mismatch')
        if self.record.get('window') not in (None, receipt['window']):
            raise RecoveryStop('window_changed_during_recovery')
        self.record['window'] = receipt['window']
        entry.update(returncode=code, status=receipt['status'], receipt=receipt,
                     receipt_sha256=hashlib.sha256(raw).hexdigest(),
                     completed_at=receipt['completed_at'], actual_requests=count,
                     openalex_requests=oa, responses_cached=receipt['responses_cached'])
        if code == 0 and (receipt['status'] != 'complete' or receipt['deferred_tasks']):
            raise RecoveryStop('false_success_receipt')
        if code != 0 and receipt['status'] == 'complete':
            raise RecoveryStop('nonzero_exit_after_complete_receipt')
        return receipt, state

    def run(self):
        try:
            self.save()  # Durable invocation identity before any provider work.
            for number in range(1, self.max_passes + 1):
                self.wait_for_hold()
                if self.remaining() < 240:
                    raise RecoveryStop('recovery_runtime_budget')
                before = read_json(self.data / 'discovery_checkpoint.json', {})
                before_count = len(before.get('responses', {}))
                before_tasks = len(before.get('tasks', {}))
                before_window = before.get('window')
                del before
                entry = {'pass_id': self.record['run_id'] + ':' + str(number),
                         'number': number, 'status': 'started', 'started_at': self.timestamp()}
                self.record['passes'].append(entry)
                self.save()
                # Publishing the start marker can take time. Recompute after
                # it completes; never let that overhead extend provider work.
                runtime = min(self.pass_seconds, int(self.remaining() - 180))
                if runtime < 60:
                    raise RecoveryStop('recovery_runtime_budget')
                code = self.invoke(entry['pass_id'], runtime)
                receipt, state = self.verify(entry, code, runtime)
                if before_window != receipt['window']:
                    before_count = before_tasks = 0
                progress = len(state['responses']) > before_count or len(state['tasks']) > before_tasks
                entry['made_progress'] = progress
                del state
                self.save()  # A failed push forbids the next pass.
                if code == 0:
                    self.record['status'] = 'complete'
                    self.record['completed_at'] = self.timestamp()
                    self.save()
                    return 0
                reasons = set(receipt['deferred_tasks'].values())
                if any(r.get('http_status') in (401, 403) for r in receipt['requests']):
                    raise RecoveryStop('provider_access_or_quota_requires_review')
                if not reasons or not reasons <= {'runtime_budget', 'request_budget',
                                                  'openalex_request_budget', 'openalex_cooldown'}:
                    raise RecoveryStop('non_recoverable_pass_failure')
                if 'openalex_cooldown' in reasons:
                    if self.hold()[0] <= self.clock():
                        raise RecoveryStop('cooldown_without_future_deadline')
                elif not progress:
                    raise RecoveryStop('no_progress')
                print(f'Recovery pass {number} saved; remaining work will resume within bounds', flush=True)
            raise RecoveryStop('pass_limit')
        except Exception as error:
            reason = str(error) if isinstance(error, RecoveryStop) else type(error).__name__
            self.record.update(status='blocked', reason=reason, completed_at=self.timestamp())
            try:
                self.save(remote=not self.sync_failed)
            except RecoveryStop:
                self.record.update(status='blocked', reason='state_sync_failed')
                self.save(remote=False)
            print('Discovery recovery stopped: ' + self.record['reason'], flush=True)
            return 1


def main(root=None):
    root = Path(root) if root is not None else Path(__file__).resolve().parents[2]
    try:
        recovery = Recovery(root)
    except Exception as error:
        # Preserve corrupt input rather than replacing the ledger or claiming
        # a pass ran. The always-uploaded artifact makes startup failures visible.
        atomic_json(root / 'data/discovery_recovery_startup_error.json', {
            'status': 'blocked', 'reason': 'recovery_initialization_failed',
            'error_type': type(error).__name__,
            'run_id': os.getenv('GITHUB_RUN_ID'), 'attempt': os.getenv('GITHUB_RUN_ATTEMPT')})
        print('Discovery recovery initialization failed: ' + type(error).__name__, flush=True)
        return 1
    code = recovery.run()
    summary = os.getenv('GITHUB_STEP_SUMMARY')
    if summary:
        with open(summary, 'a') as out:
            out.write('Discovery recovery: ' + recovery.record['status'] + '\n\n')
            out.write('Passes: ' + str(len(recovery.record['passes'])) + '\n\n')
            if recovery.record.get('reason'):
                out.write('Stopped: ' + recovery.record['reason'] + '\n')
    return code


if __name__ == '__main__':
    raise SystemExit(main())

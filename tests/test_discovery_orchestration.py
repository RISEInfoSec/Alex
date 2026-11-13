"""No live providers: real persisted receipts/ledger drive all transitions."""
import json
from datetime import datetime, timezone

import pytest

from alex.pipelines.discovery_recovery import Recovery, RecoveryStop
from alex.utils.discovery_checkpoint import atomic_json


class Clock:
    def __init__(self):
        self.now = 1800000000
        self.waits = []

    def read(self):
        return self.now

    def sleep(self, delay):
        assert 0 < delay <= 60
        self.waits.append(delay)
        self.now += delay


@pytest.fixture
def setup(tmp_path):
    atomic_json(tmp_path / 'config/weekly_recovery_policy.json', {
        'max_passes': 3, 'max_runtime_seconds': 900,
        'max_cooldown_wait_seconds': 120, 'max_cooldown_resumptions': 1})
    atomic_json(tmp_path / 'config/weekly_discovery_policy.json', {
        'runtime_seconds': 60, 'max_requests': 3, 'openalex_max_requests': 2})
    atomic_json(tmp_path / 'config/openalex_request_policy.json', {'retry_not_before': None})
    atomic_json(tmp_path / 'data/discovery_checkpoint.json', {
        'window': {'from_date': '2026-10-29', 'until_date': '2026-11-05'},
        'status': 'partial', 'responses': {'retained-404': None}, 'tasks': {'Crossref:q': []}})
    return tmp_path, Clock(), []


def build(setup, *, invoke=None, publish=None, run_id='run:1'):
    root, clock, pushes = setup
    return Recovery(root, invoke=invoke, publish=publish or (lambda: pushes.append('push')),
                    clock=clock.read, monotonic=clock.read, sleep=clock.sleep, run_id=run_id)


def result(root, clock, pass_id, runtime, *, reason=None, status_code=200, add=True):
    state = json.loads((root / 'data/discovery_checkpoint.json').read_text())
    state['orchestration_pass_id'] = pass_id
    state['status'] = 'partial' if reason else 'complete'
    if add:
        state['responses'][pass_id] = {'title': 'Retained response ' + pass_id}
    atomic_json(root / 'data/discovery_checkpoint.json', state)
    receipt = {'schema_version': 1, 'orchestration_pass_id': pass_id,
               'window': state['window'], 'status': state['status'],
               'completed_at': datetime.fromtimestamp(clock.now, timezone.utc).isoformat(),
               'responses_cached': len(state['responses']), 'completed_tasks': len(state['tasks']),
               'actual_request_count': 1 if add else 0, 'openalex_request_count': 1 if add else 0,
               'requests': [{'host': 'api.openalex.org', 'http_status': status_code}] if add else [],
               'budgets': {'runtime_seconds': runtime, 'max_requests': 3, 'openalex_max_requests': 2},
               'deferred_tasks': {'OpenAlex:abstracts': reason} if reason else {}}
    atomic_json(root / 'data/discovery_run_receipt.json', receipt)
    return 1 if reason else 0


def test_budget_partial_resumes_without_losing_cached_missing_result(setup):
    root, clock, pushes = setup
    calls = []
    def invoke(pass_id, runtime):
        calls.append(pass_id)
        return result(root, clock, pass_id, runtime,
                      reason='openalex_request_budget' if len(calls) == 1 else None)
    recovery = build(setup, invoke=invoke)
    assert recovery.run() == 0
    assert len(calls) == 2
    state = json.loads((root / 'data/discovery_checkpoint.json').read_text())
    assert state['responses']['retained-404'] is None
    assert all(key in state['responses'] for key in calls)
    assert len(pushes) >= 6
    ledger = json.loads((root / 'data/discovery_recovery_ledger.json').read_text())
    assert ledger['runs'][0]['status'] == 'complete'
    assert [p['actual_requests'] for p in ledger['runs'][0]['passes']] == [1, 1]
    assert all('receipt_sha256' in p for p in ledger['runs'][0]['passes'])
    with pytest.raises(ValueError, match='already recorded'):
        build(setup, invoke=invoke)


def test_shared_run_budget_stops_without_another_pass(setup):
    root, clock, _ = setup
    calls = []
    def invoke(pass_id, runtime):
        calls.append(pass_id)
        return result(root, clock, pass_id, runtime,
                      reason='openalex_request_budget' if len(calls) == 1
                      else 'openalex_run_request_budget')
    recovery = build(setup, invoke=invoke)
    assert recovery.run() == 1
    assert len(calls) == 2
    assert recovery.record['status'] == 'blocked'
    assert recovery.record['reason'] == 'openalex_run_request_budget'
    state = json.loads((root / 'data/discovery_checkpoint.json').read_text())
    assert state['responses']['retained-404'] is None
    assert all(key in state['responses'] for key in calls)
    ledger = json.loads((root / 'data/discovery_recovery_ledger.json').read_text())
    assert ledger['runs'][0]['reason'] == 'openalex_run_request_budget'
    assert len(ledger['runs'][0]['passes']) == 2


def test_interrupted_pass_preserves_results_for_next_invocation(setup):
    root, clock, _ = setup
    def interrupted(pass_id, runtime):
        result(root, clock, pass_id, runtime, reason='runtime_budget')
        raise RecoveryStop('child_timeout')
    first = build(setup, invoke=interrupted)
    assert first.run() == 1
    assert first.record['reason'] == 'child_timeout'
    second = build(setup, run_id='run:2',
                   invoke=lambda p, r: result(root, clock, p, r))
    assert second.run() == 0
    state = json.loads((root / 'data/discovery_checkpoint.json').read_text())
    assert set(state['responses']) == {'retained-404', 'run:1:1', 'run:2:1'}
    ledger = json.loads((root / 'data/discovery_recovery_ledger.json').read_text())
    assert [r['status'] for r in ledger['runs']] == ['blocked', 'complete']


def test_one_transient_cooldown_wait_then_resume(setup):
    root, clock, _ = setup
    calls = []
    def invoke(pass_id, runtime):
        calls.append(clock.now)
        if len(calls) == 1:
            atomic_json(root / 'data/discovery_openalex_state.json', {
                'retry_not_before': clock.now + 90, 'last_failure': 'network_or_timeout'})
            return result(root, clock, pass_id, runtime, reason='openalex_cooldown')
        return result(root, clock, pass_id, runtime)
    recovery = build(setup, invoke=invoke)
    assert recovery.run() == 0
    assert calls[1] - calls[0] == 90
    assert clock.waits == [60, 30]
    assert recovery.record['cooldown_resumptions'] == 1


@pytest.mark.parametrize('failure', ['HTTP401', 'HTTP403', 'quota_exhausted'])
def test_access_and_quota_hold_send_no_request(setup, failure):
    root, clock, _ = setup
    atomic_json(root / 'data/discovery_openalex_state.json', {
        'retry_not_before': clock.now + 30, 'last_failure': failure})
    recovery = build(setup, invoke=lambda *a: pytest.fail('must not send'))
    assert recovery.run() == 1
    assert recovery.record['reason'] == 'provider_access_or_quota_requires_review'
    assert not clock.waits


def test_long_hold_stops_without_spending_the_runner_budget(setup):
    root, clock, _ = setup
    atomic_json(root / 'data/discovery_openalex_state.json', {
        'retry_not_before': clock.now + 3600, 'last_failure': 'HTTP429'})
    recovery = build(setup, invoke=lambda *a: pytest.fail('must not send'))
    assert recovery.run() == 1
    assert recovery.record['reason'] == 'cooldown_exceeds_run_budget'
    assert not clock.waits


def test_second_cooldown_does_not_loop(setup):
    root, clock, _ = setup
    def invoke(p, runtime):
        atomic_json(root / 'data/discovery_openalex_state.json', {
            'retry_not_before': clock.now + 10, 'last_failure': 'HTTP503'})
        return result(root, clock, p, runtime, reason='openalex_cooldown')
    recovery = build(setup, invoke=invoke)
    assert recovery.run() == 1
    assert recovery.record['reason'] == 'cooldown_resumption_limit'
    assert len(recovery.record['passes']) == 2


def test_failed_checkpoint_forbids_next_pass(setup):
    root, clock, pushes = setup
    def publish():
        pushes.append('push')
        if len(pushes) == 3:
            raise RuntimeError('remote rejected stale writer')
    recovery = build(setup, publish=publish,
        invoke=lambda p, r: result(root, clock, p, r, reason='openalex_request_budget'))
    assert recovery.run() == 1
    assert recovery.record['reason'] == 'state_sync_failed'
    assert len(recovery.record['passes']) == 1
    assert len(pushes) == 3  # No blind repeat of the failed write.


@pytest.mark.parametrize('fault', ['stale', 'corrupt', 'counts', 'false_success', 'exit_after_complete', 'signal'])
def test_bad_receipt_never_releases_downstream_or_retries(setup, fault):
    root, clock, _ = setup
    def invoke(p, runtime):
        code = result(root, clock, p, runtime)
        path = root / 'data/discovery_run_receipt.json'
        r = json.loads(path.read_text())
        if fault == 'signal': return -15
        if fault == 'stale': r['orchestration_pass_id'] = 'old'
        if fault == 'counts': r['actual_request_count'] += 1
        if fault == 'false_success':
            code = 0
            result(root, clock, p, runtime, reason='openalex_request_budget')
            return code
        if fault == 'exit_after_complete': return 1
        if fault == 'corrupt': path.write_text('{truncated')
        else: atomic_json(path, r)
        return code
    recovery = build(setup, invoke=invoke)
    assert recovery.run() == 1
    assert recovery.record['status'] == 'blocked'
    assert len(recovery.record['passes']) == 1


def test_zero_progress_and_unknown_errors_stop(setup):
    root, clock, _ = setup
    recovery = build(setup, invoke=lambda p, r: result(root, clock, p, r,
                                    reason='runtime_budget', add=False))
    assert recovery.run() == 1
    assert recovery.record['reason'] == 'no_progress'
    second = build(setup, run_id='run:2', invoke=lambda p, r: result(root, clock, p, r,
                                                   reason='invalid_xml_response'))
    assert second.run() == 1
    assert second.record['reason'] == 'non_recoverable_pass_failure'


def test_hard_pass_limit_remains_a_failure(setup):
    root, clock, _ = setup
    recovery = build(setup, invoke=lambda p, r: result(root, clock, p, r,
                                             reason='openalex_request_budget'))
    assert recovery.run() == 1
    assert recovery.record['reason'] == 'pass_limit'
    assert len(recovery.record['passes']) == 3


def test_shared_coordinator_hold_stops_even_when_another_source_made_progress(setup):
    root, clock, _ = setup
    calls=[]
    def invoke(pass_id, runtime):
        calls.append(pass_id)
        code=result(root, clock, pass_id, runtime, reason='openalex_shared_coordinator_required')
        path=root/'data/discovery_run_receipt.json';receipt=json.loads(path.read_text())
        receipt['requests'][0]['host']='api.crossref.org';receipt['openalex_request_count']=0
        atomic_json(path,receipt)
        return code
    recovery=build(setup,invoke=invoke)
    assert recovery.run()==1
    assert len(calls)==1
    assert recovery.record['reason']=='openalex_shared_coordinator_required'


def test_recovery_time_budget_shortens_final_pass_then_stops(setup):
    root, clock, _ = setup
    calls = []
    def invoke(p, runtime):
        calls.append(runtime)
        clock.now += 700
        return result(root, clock, p, runtime, reason='runtime_budget')
    recovery = build(setup, invoke=invoke)
    assert recovery.run() == 1
    assert recovery.record['reason'] == 'recovery_runtime_budget'
    assert calls == [60]


def test_bounds_cannot_be_silently_increased(setup):
    root, _, _ = setup
    p = root / 'config/weekly_recovery_policy.json'
    policy = json.loads(p.read_text()); policy['max_passes'] = 100
    atomic_json(p, policy)
    with pytest.raises(ValueError): build(setup)


@pytest.mark.parametrize('clock_start', [4.001, 10000.0])
def test_real_discovery_crosses_request_cap_and_reuses_responses(setup, monkeypatch, clock_start):
    from unittest.mock import MagicMock
    import pandas as pd
    import requests
    from alex.pipelines import discovery
    from alex.utils import io, http
    from alex.utils.discovery_checkpoint import DiscoveryIncomplete
    root, _, _ = setup
    (root / 'data/discovery_checkpoint.json').unlink()
    registry = {'queries': ['osint'], 'connectors': {k: {'enabled': k == 'crossref'}
        for k in ('openalex', 'crossref', 'arxiv_rss', 'zenodo', 'github', 'core', 'semantic_scholar')}}
    atomic_json(root / 'config/query_registry.json', registry)
    monkeypatch.setattr(io, 'ROOT', root)
    monkeypatch.setattr(http, 'CACHE', root / 'cache.json')
    # Exercise the historical pacing protocol with a mocked HTTP transport.
    monkeypatch.setattr(http, '_shared_coordinator_unavailable', lambda: False)
    monkeypatch.setattr(http, '_openalex_policy', lambda: {
        'requests_enabled': True, 'min_interval_seconds': 0, 'request_timeout_seconds': 20,
        'failure_cooldown_seconds': 3600, 'retry_not_before': None})
    monkeypatch.setattr(http.time, 'sleep', lambda _: None)
    # Adding/subtracting a float deadline can reconstruct60 as60.00000000000001.
    # A legitimate configured bound must not intermittently fail verification.
    monkeypatch.setattr(http.time, 'monotonic', lambda: clock_start)
    monkeypatch.delenv('ALEX_DISCOVERY_SYNC', raising=False)
    monkeypatch.setenv('ALEX_OPENALEX_STATE_PATH', str(root / 'data/discovery_openalex_state.json'))
    search = MagicMock(return_value=[{'title': ['OSINT research ' + n], 'DOI': '10.1/' + n}
                                   for n in ('a', 'b', 'c')])
    monkeypatch.setattr(discovery.crossref, 'search', search)
    calls = []
    def get(session, url, **kwargs):
        calls.append(url)
        r = MagicMock(status_code=200, headers={})
        r.json.return_value = {'ids': {'doi': url.split('/works/')[1]},
                              'abstract_inverted_index': {'Recovered': [0], 'abstract': [1]}}
        return r
    monkeypatch.setattr(requests.Session, 'get', get)
    def invoke(pass_id, runtime):
        monkeypatch.setenv('ALEX_DISCOVERY_PASS_ID', pass_id)
        monkeypatch.setenv('ALEX_DISCOVERY_RUNTIME_LIMIT', str(runtime))
        try:
            discovery.run()
        except DiscoveryIncomplete:
            return 1
        return 0
    recovery = build(setup, invoke=invoke)
    assert recovery.run() == 0
    assert [p['actual_requests'] for p in recovery.record['passes']] == [2, 1]
    assert len(calls) == len(set(calls)) == 3
    assert search.call_count == 1
    result_frame = pd.read_csv(root / 'data/discovery_candidates.csv')
    assert list(result_frame['abstract']) == ['Recovered abstract'] * 3

    # Reproduce a completed old window rejected by the pre-fix controller.
    import math
    previous = recovery.record
    previous.update(run_id='123:1', status='blocked', reason='receipt_budget_mismatch')
    previous['passes'][-1].update(pass_id='123:1:2', status='started')
    old_window = {'from_date': '2026-10-29', 'until_date': '2026-11-05'}
    previous['window'] = old_window
    atomic_json(recovery.path, previous)
    for name in ('discovery_checkpoint.json', 'discovery_run_receipt.json'):
        path = root / 'data' / name
        saved = json.loads(path.read_text())
        saved.update(window=old_window, orchestration_pass_id='123:1:2')
        if name == 'discovery_run_receipt.json':
            saved['budgets']['runtime_seconds'] = math.nextafter(60.0, math.inf)
        atomic_json(path, saved)
    prior_receipt = (root / 'data/discovery_run_receipt.json').read_bytes()
    monkeypatch.setenv('ALEX_RESUME_DISCOVERY_RUN', '123')
    monkeypatch.setenv('ALEX_DISCOVERY_REPLAY_RUN', '123')
    replay = build(setup, invoke=invoke, run_id='124:1')
    assert replay.run() == 0
    assert len(replay.record['passes']) == 1
    final = replay.record['passes'][0]['receipt']
    assert final['window'] == old_window
    assert final['actual_request_count'] == final['openalex_request_count'] == 0
    assert final['budgets']['max_requests'] == final['budgets']['openalex_max_requests'] == 0
    assert len(calls) == 3 and search.call_count == 1
    import hashlib
    evidence = replay.record['completed_window_reconciliation']
    assert evidence['prior_final_pass']['receipt_sha256'] == hashlib.sha256(prior_receipt).hexdigest()
    assert evidence['prior_recovery']['reason'] == 'receipt_budget_mismatch'


@pytest.mark.parametrize('fault', ['wrong_run', 'partial', 'unknown_failure', 'over_budget',
                                  'counts', 'provider_error', 'elapsed', 'window'])
def test_completed_replay_rejects_invalid_evidence_before_writing(setup, monkeypatch, fault):
    import math
    root, clock, _ = setup
    result(root, clock, '123:1:1', math.nextafter(60.0, math.inf))
    receipt_path = root / 'data/discovery_run_receipt.json'
    receipt = json.loads(receipt_path.read_text())
    receipt['elapsed_seconds'] = 10
    prior = {'run_id': '123:1', 'status': 'blocked', 'reason': 'receipt_budget_mismatch',
             'window': receipt['window'], 'passes': [{'pass_id': '123:1:1', 'status': 'started'}]}
    if fault == 'partial': receipt['status'] = 'partial'
    if fault == 'unknown_failure': prior['reason'] = 'unknown'
    if fault == 'over_budget': receipt['budgets']['runtime_seconds'] = 61
    if fault == 'counts': receipt['actual_request_count'] = 2
    if fault == 'provider_error': receipt['requests'][0]['http_status'] = 403
    if fault == 'elapsed': receipt['elapsed_seconds'] = 61
    if fault == 'window': prior['window'] = {}
    atomic_json(receipt_path, receipt)
    path = root / 'data/discovery_recovery_receipt.json'
    atomic_json(path, prior)
    before = path.read_bytes()
    monkeypatch.setenv('ALEX_RESUME_DISCOVERY_RUN', '999' if fault == 'wrong_run' else '123')
    with pytest.raises(RecoveryStop):
        build(setup)
    assert path.read_bytes() == before


def test_completed_replay_cache_miss_sends_nothing(tmp_path, monkeypatch):
    import requests
    from alex.utils import http
    from alex.utils.discovery_checkpoint import DiscoveryClient, DiscoveryDeferred
    monkeypatch.setattr(http, 'CACHE', tmp_path / 'cache.json')
    monkeypatch.setattr(requests.Session, 'get', lambda *a, **kw: pytest.fail('No network allowed'))
    client = DiscoveryClient(tmp_path / 'checkpoint.json', {}, {},
                             {'max_requests': 0, 'openalex_max_requests': 0})
    with pytest.raises(DiscoveryDeferred, match='request_budget'):
        client.get_json('https://api.openalex.org/works/https://doi.org/10.1/missing')
    assert client.requests == []


def test_timed_out_subprocess_is_terminated_before_return(setup, monkeypatch):
    import signal
    import subprocess
    from unittest.mock import MagicMock
    recovery = build(setup)
    process = MagicMock(pid=999999)
    process.__enter__.return_value = process
    process.wait.side_effect = [subprocess.TimeoutExpired('child', 210),
                               subprocess.TimeoutExpired('child', 10), -9]
    monkeypatch.setattr('alex.pipelines.discovery_recovery.subprocess.Popen', lambda *a, **kw: process)
    kill = MagicMock()
    monkeypatch.setattr('alex.pipelines.discovery_recovery.os.killpg', kill)
    with pytest.raises(RecoveryStop, match='child_timeout'):
        recovery._invoke('pass', 60)
    assert [c.args for c in kill.call_args_list] == [(999999, signal.SIGTERM), (999999, signal.SIGKILL)]
    assert process.wait.call_count == 3


def test_startup_failure_retains_corrupt_ledger_and_records_artifact(setup):
    from alex.pipelines.discovery_recovery import main
    root, _, _ = setup
    ledger = root / 'data/discovery_recovery_ledger.json'
    ledger.write_text('{truncated')
    assert main(root) == 1
    assert ledger.read_text() == '{truncated'
    evidence = json.loads((root / 'data/discovery_recovery_startup_error.json').read_text())
    assert evidence['reason'] == 'recovery_initialization_failed'
    assert evidence['error_type'] == 'JSONDecodeError'


def test_slow_checkpoint_shortens_child_runtime(setup):
    root, clock, _ = setup
    atomic_json(root / 'config/weekly_discovery_policy.json', {
        'runtime_seconds': 2700, 'max_requests': 3, 'openalex_max_requests': 2})
    runtimes = []
    def publish(): clock.now += 100
    def invoke(p, runtime):
        runtimes.append(runtime)
        return result(root, clock, p, runtime)
    recovery = build(setup, invoke=invoke, publish=publish)
    assert recovery.run() == 0
    assert runtimes == [520]  # 900 total minus two100-second pushes and180 reserve.


def test_completed_recovery_records_initial_and_final_candidate_hashes(setup):
    import hashlib
    root,clock,_=setup
    source=root/'data/discovery_candidates.csv';source.write_bytes(b'title\nBefore\n')
    initial=hashlib.sha256(source.read_bytes()).hexdigest()
    def invoke(pass_id,runtime):
        source.write_bytes(b'title\nAfter\n')
        return result(root,clock,pass_id,runtime)
    recovery=build(setup,invoke=invoke)
    assert recovery.run()==0
    receipt=json.loads((root/'data/discovery_recovery_receipt.json').read_text())
    assert receipt['starting_candidates_sha256']==initial
    assert receipt['final_candidates_sha256']==hashlib.sha256(source.read_bytes()).hexdigest()

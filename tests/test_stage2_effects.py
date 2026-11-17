"""Crash, response retention, explicit retry and no duplicate paid-send gates."""
import json
import os
from pathlib import Path
import signal
import sqlite3
import subprocess
import sys
import time

import pytest

from stage1.engine import digest
from stage2.effects import EffectHeld, EffectLedger


REQUEST = {'provider': 'recorded-paid-fixture', 'operation': 'classify',
           'input': {'content_hash': 'a' * 64, 'model': 'fixture-model', 'prompt_hash': 'b' * 64},
           'contract': 'strict-category-v1'}


def ledger(path):
    db = sqlite3.connect(path, isolation_level=None)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA foreign_keys=ON')
    db.execute('PRAGMA journal_mode=WAL')
    db.execute('PRAGMA synchronous=FULL')
    return EffectLedger(db)


def validate(response):
    if set(response['body']) != {'category', 'input_hash', 'tokens'}:
        raise ValueError('invalid_paid_response')
    if (response['body']['category'] not in ('OSINT', 'Cybercrime', 'Other') or
            response['body']['input_hash'] != REQUEST['input']['content_hash'] or
            type(response['body']['tokens']) is not int or response['body']['tokens'] <= 0):
        raise ValueError('invalid_paid_response')


def successful():
    return {'status': 200, 'body': {'category': 'OSINT', 'input_hash': 'a' * 64, 'tokens': 23}}


def test_received_paid_result_is_reused_across_process_connections(tmp_path):
    path = tmp_path / 'effects.sqlite'
    first = ledger(path)
    sends = []
    result = first.request(REQUEST, lambda r: sends.append(r) or successful(), validate)
    first.db.close()
    second = ledger(path)
    assert second.request(REQUEST, lambda r: pytest.fail('duplicate paid transport'), validate) == result
    assert len(sends) == 1
    assert second.db.execute('SELECT attempts FROM external_effects').fetchone()[0] == 1
    assert json.loads(second.db.execute('SELECT response FROM external_effects').fetchone()[0])['body']['tokens'] == 23
    second.db.close()


@pytest.mark.parametrize('status', [401, 403, 429, 500])
def test_received_error_is_retained_and_never_automatically_retried(tmp_path, status):
    l = ledger(tmp_path / 'effects.sqlite')
    sends = []
    response = {'status': status, 'body': {'error': 'controlled failure'}, 'retry_after_seconds': 30}
    with pytest.raises(EffectHeld):
        l.request(REQUEST, lambda r: sends.append(r) or response, validate, now=100)
    for now in (101, 10000):
        with pytest.raises(EffectHeld):
            l.request(REQUEST, lambda r: pytest.fail('automatic retry'), validate, now=now)
    row = l.db.execute('SELECT * FROM external_effects').fetchone()
    assert json.loads(row['response']) == response and row['response_hash'] == digest(response)
    assert len(sends) == 1
    receipt = {'id': 'controlled-reconciliation', 'actor': 'synthetic-operator',
               'reason': 'Controlled retry of received fixture failure', 'request_hash': digest(REQUEST),
               'finding': 'retry_received_failure', 'response_hash': row['response_hash']}
    if status in (401, 403, 429):
        with pytest.raises(EffectHeld, match='separate_authorization'):
            l.authorize_retry(REQUEST, receipt, now=10000)
    else:
        with pytest.raises(EffectHeld, match='cooldown'):
            l.authorize_retry(REQUEST, receipt, now=101)
        l.authorize_retry(REQUEST, receipt, now=131)
        assert l.request(REQUEST, lambda r: successful(), validate, now=132) == successful()
        assert l.db.execute('SELECT attempts FROM external_effects').fetchone()[0] == 2
        with pytest.raises(sqlite3.IntegrityError, match='immutable'):
            l.db.execute("DELETE FROM external_effect_events")
    l.db.close()


def test_malformed_and_wrong_input_paid_results_cannot_synthesize_other(tmp_path):
    for index, body in enumerate([{}, {'category': 'OSINT', 'input_hash': 'wrong', 'tokens': 1},
                                   {'category': 'Made up', 'input_hash': 'a' * 64, 'tokens': 3}]):
        l = ledger(tmp_path / f'effect-{index}.sqlite')
        with pytest.raises(EffectHeld):
            l.request(REQUEST, lambda r: {'status': 200, 'body': body}, validate)
        row = l.db.execute('SELECT response,state FROM external_effects').fetchone()
        assert row['state'] == 'held' and json.loads(row['response'])['body'] == body
        assert l.db.execute('SELECT count(*) FROM external_effect_events').fetchone()[0] == 2
        l.db.close()


def test_timeout_remains_ambiguous_across_restart(tmp_path):
    path = tmp_path / 'effects.sqlite'
    l = ledger(path)
    def timeout(_):
        raise TimeoutError('controlled response lost after send')
    with pytest.raises(TimeoutError):
        l.request(REQUEST, timeout, validate)
    l.db.close()
    l = ledger(path)
    with pytest.raises(EffectHeld, match='unknown'):
        l.request(REQUEST, lambda r: pytest.fail('duplicate uncertain send'), validate)
    with pytest.raises(ValueError, match='receipt_required'):
        l.authorize_retry(REQUEST, {})
    assert l.db.execute('SELECT attempts FROM external_effects').fetchone()[0] == 1
    l.db.close()


def test_real_sigkill_after_reservation_never_reissues_paid_work(tmp_path):
    path = tmp_path / 'effects.sqlite'
    marker = tmp_path / 'transport-started'
    program = '''
import pathlib,sqlite3,sys,time
from stage2.effects import EffectLedger
from tests.test_stage2_effects import REQUEST,validate
db=sqlite3.connect(sys.argv[1],isolation_level=None);db.row_factory=sqlite3.Row
def transport(request):
 pathlib.Path(sys.argv[2]).write_text('recorded transport entered')
 time.sleep(30)
ledger=EffectLedger(db);ledger.request(REQUEST,transport,validate)
'''
    child = subprocess.Popen([sys.executable, '-c', program, str(path), str(marker)])
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and child.poll() is None and time.monotonic() < deadline:
            time.sleep(.02)
        assert marker.exists(), 'reservation_test_child_failed'
        child.kill()
        assert child.wait(timeout=5) == -signal.SIGKILL
    finally:
        if child.poll() is None:
            child.kill()
            child.wait(timeout=5)
    l = ledger(path)
    with pytest.raises(EffectHeld, match='unresolved'):
        l.request(REQUEST, lambda r: pytest.fail('duplicate work after process death'), validate)
    row = l.db.execute('SELECT state,attempts,response FROM external_effects').fetchone()
    assert tuple(row) == ('running', 1, None)
    l.db.close()


def test_active_request_is_fenced_and_request_credentials_are_rejected(tmp_path):
    path = tmp_path / 'effects.sqlite'
    l = ledger(path)
    second = ledger(path)
    def during_dispatch(_):
        with pytest.raises(EffectHeld):
            second.request(REQUEST, lambda r: pytest.fail('concurrent duplicate'), validate)
        return successful()
    assert l.request(REQUEST, during_dispatch, validate) == successful()
    bad = dict(REQUEST, input={'api_key': 'synthetic-must-not-be-persisted'})
    with pytest.raises(ValueError, match='credential'):
        l.request(bad, lambda r: pytest.fail('credential transport'), validate)
    assert l.db.execute('SELECT count(*) FROM external_effects').fetchone()[0] == 1
    second.db.close()
    l.db.close()


def test_explicit_retry_has_finite_attempt_ceiling_and_preserves_prior_responses(tmp_path):
    l = ledger(tmp_path / 'effects.sqlite')
    for attempt in range(3):
        response = {'status': 500, 'body': {'fixture_attempt': attempt}}
        with pytest.raises(EffectHeld):
            l.request(REQUEST, lambda r: response, validate, now=100 + attempt)
        row = l.db.execute('SELECT * FROM external_effects').fetchone()
        receipt = {'id': 'retry-' + str(attempt), 'actor': 'synthetic-operator', 'reason': 'Controlled fixture retry',
                   'request_hash': digest(REQUEST), 'finding': 'retry_received_failure', 'response_hash': row['response_hash']}
        if attempt < 2:
            l.authorize_retry(REQUEST, receipt, now=100 + attempt)
        else:
            with pytest.raises(EffectHeld, match='attempt_bound'):
                l.authorize_retry(REQUEST, receipt, now=10000)
    assert l.db.execute('SELECT attempts FROM external_effects').fetchone()[0] == 3
    previous = [json.loads(r[0]) for r in l.db.execute("SELECT receipt FROM external_effect_events WHERE event='prior_outcome'")]
    assert [json.loads(p['response'])['body']['fixture_attempt'] for p in previous] == [0, 1]
    l.db.close()


def test_response_hash_corruption_stops_reuse_without_send(tmp_path):
    l = ledger(tmp_path / 'effects.sqlite')
    l.request(REQUEST, lambda r: successful(), validate)
    l.db.execute("UPDATE external_effects SET response='{}'")
    with pytest.raises(ValueError, match='response_hash_mismatch'):
        l.request(REQUEST, lambda r: pytest.fail('retry corrupt cache'), validate)
    l.db.close()

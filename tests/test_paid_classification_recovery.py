import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock
import threading

import pandas as pd
import pytest
import requests

from alex.pipelines import classify
from alex.utils import io
from alex.utils.paid_classification import Ledger, PaidRequestHeld, digest

VALID = {'Category': 'Other', 'Investigation_Type': 'Other', 'OSINT_Source_Types': []}


def response(value=VALID):
    r = MagicMock(ok=True, status_code=200)
    r.json.return_value = {'id': 'resp_retained', 'status': 'completed', 'output_text': json.dumps(value),
                           'usage': {'input_tokens': 10, 'output_tokens': 5, 'total_tokens': 15}}
    return r


@pytest.fixture
def corpus(tmp_path, monkeypatch):
    monkeypatch.setattr(io, 'ROOT', tmp_path)
    monkeypatch.setenv('OPENAI_API_KEY', 'test-key')
    monkeypatch.delenv('ALEX_DISCOVERY_SYNC', raising=False)
    monkeypatch.delenv('ALEX_CLASSIFICATION_SYNC', raising=False)
    monkeypatch.setattr(classify, 'CLASSIFY_WORKERS', 1)
    (tmp_path / 'data').mkdir()
    pd.DataFrame([{'title': 'Paper A', 'abstract': 'A retained abstract', 'venue': 'IEEE',
                   'authors': 'A', 'citation_count': 1, 'doi': '10.1/a'}]).to_csv(
        tmp_path / 'data/accepted_harvested.csv', index=False)
    return tmp_path


def test_exact_paid_response_reused_without_credentials_or_new_charge(corpus, monkeypatch):
    paid = MagicMock(return_value=response())
    monkeypatch.setattr(classify.requests, 'post', paid)
    classify.run()
    assert paid.call_count == 1
    assert 'test-key' not in (corpus / 'data/classification_request_ledger.json').read_text()
    original = (corpus / 'data/accepted_classified.csv').read_bytes()
    monkeypatch.delenv('OPENAI_API_KEY')
    paid.side_effect = AssertionError('Must reuse the exact verified response')
    classify.run()
    assert paid.call_count == 1
    assert classify._TOKEN_USAGE['calls'] == 0
    assert (corpus / 'data/accepted_classified.csv').read_bytes() == original


def test_changed_input_does_not_reuse_prior_paid_response(corpus, monkeypatch):
    paid = MagicMock(return_value=response())
    monkeypatch.setattr(classify.requests, 'post', paid)
    classify.run()
    path = corpus / 'data/accepted_harvested.csv'
    path.write_text(path.read_text().replace('A retained abstract', 'Changed abstract'))
    classify.run()
    assert paid.call_count == 2


@pytest.mark.parametrize('fault', ['network', 'http500', 'empty', 'malformed', 'invalid_enum', 'extra_fields',
                                  'incomplete', 'missing_id', 'refusal'])
def test_provider_failures_never_become_other_or_get_blindly_retried(corpus, monkeypatch, fault):
    r = response()
    if fault == 'http500': r.ok = False; r.status_code = 500; r.json.return_value = {}
    if fault == 'empty': r.json.return_value['output_text'] = ''
    if fault == 'malformed': r.json.return_value['output_text'] = '{broken'
    if fault == 'invalid_enum': r = response({**VALID, 'Category': 'Invented'})
    if fault == 'extra_fields': r = response({**VALID, 'Keywords': []})
    if fault == 'incomplete': r.json.return_value['status'] = 'incomplete'
    if fault == 'missing_id': del r.json.return_value['id']
    if fault == 'refusal': r.json.return_value['output'] = [{'content': [{'type': 'refusal'}]}]
    paid = MagicMock(return_value=r)
    if fault == 'network': paid.side_effect = requests.ConnectionError('ambiguous response')
    monkeypatch.setattr(classify.requests, 'post', paid)
    with pytest.raises(classify.OpenAIClassificationError): classify.run()
    assert not (corpus / 'data/accepted_classified.csv').exists()
    count = paid.call_count
    with pytest.raises(PaidRequestHeld): classify.run()
    assert paid.call_count == count == 1


def test_quota_failure_retains_success_and_unstarted_work(corpus, monkeypatch, capsys):
    path = corpus / 'data/accepted_harvested.csv'
    rows = pd.read_csv(path).to_dict('records')
    rows += [{**rows[0], 'title': 'Paper B'}, {**rows[0], 'title': 'Paper C'}]
    pd.DataFrame(rows).to_csv(path, index=False)
    quota = MagicMock(ok=False, status_code=429)
    quota.json.return_value = {'error': {'code': 'insufficient_quota'}}
    paid = MagicMock(side_effect=[response(), quota])
    monkeypatch.setattr(classify.requests, 'post', paid)
    with pytest.raises(classify.OpenAIQuotaError): classify.run()
    assert 'OpenAI usage: 2 send attempts; 1 usage reports; 10 input + 5 output = 15 reported tokens' in capsys.readouterr().out
    assert paid.call_count == 2
    ledger = json.loads((corpus / 'data/classification_request_ledger.json').read_text())
    assert sorted(e['status'] for e in ledger['entries'].values()) == ['complete', 'held', 'not_sent']
    assert not (corpus / 'data/accepted_classified.csv').exists()
    # Completed evidence remains usable independently of the held request.
    pd.DataFrame(rows[:1]).to_csv(path, index=False)
    paid.side_effect = AssertionError('No additional paid request')
    classify.run()
    assert paid.call_count == 2


def test_duplicate_concurrent_requests_share_one_paid_response(tmp_path):
    body = {'model': 'test', 'input': 'exact'}
    ledger = Ledger(tmp_path, [digest(body)], publish=lambda: None)
    entered, release = threading.Event(), threading.Event()
    calls = []
    def send():
        calls.append(1); entered.set(); assert release.wait(3); return VALID
    with ThreadPoolExecutor(max_workers=2) as ex:
        first = ex.submit(ledger.perform, body, send, lambda x: x)
        assert entered.wait(3)
        second = ex.submit(ledger.perform, body, send, lambda x: x)
        release.set()
        assert first.result() == second.result() == VALID
    ledger.finish()
    assert calls == [1]


def test_interrupted_reservation_is_not_proof_of_no_send(tmp_path):
    body = {'input': 'reserved'}
    first = Ledger(tmp_path, [digest(body)], publish=lambda: None, identity='first')
    # Simulate runner death before a terminal checkpoint; no inferred zero calls.
    with pytest.raises(PaidRequestHeld, match='Interrupted'):
        Ledger(tmp_path, [digest(body)], publish=lambda: None, identity='second')


def test_previous_not_sent_marker_does_not_survive_a_new_interrupted_attempt(tmp_path):
    key = digest({'input': 'reserved'})
    first = Ledger(tmp_path, [key], publish=lambda: None, identity='first')
    first.finish(failed=True)
    second = Ledger(tmp_path, [key], publish=lambda: None, identity='second')
    assert key not in second.state['entries']
    with pytest.raises(PaidRequestHeld, match='Interrupted'):
        Ledger(tmp_path, [key], publish=lambda: None, identity='third')


def test_corrupt_paid_result_and_failed_initial_push_stop_before_work(tmp_path):
    body = {'input': 'exact'}
    ledger = Ledger(tmp_path, [digest(body)], publish=lambda: None)
    ledger.perform(body, lambda: VALID, lambda x: x); ledger.finish()
    state = json.loads(ledger.path.read_text())
    state['entries'][digest(body)]['response']['Category'] = 'Invented'
    ledger.path.write_text(json.dumps(state))
    with pytest.raises(PaidRequestHeld, match='digest'):
        Ledger(tmp_path, [digest(body)], publish=lambda: None)
    def fail(): raise OSError('native state conflict')
    with pytest.raises(PaidRequestHeld, match='sync'):
        Ledger(tmp_path / 'other', [digest(body)], publish=fail)


@pytest.mark.parametrize('workflow', ['pipeline', 'classify', 'tag_new_papers'])
def test_every_production_classification_entrypoint_stops_on_remote_reservation_failure(
        tmp_path, monkeypatch, workflow):
    import subprocess
    import yaml
    from unittest.mock import Mock
    from pathlib import Path
    source = yaml.safe_load((Path(__file__).parents[1] / '.github/workflows' /
                             (workflow + '.yml')).read_text())
    monkeypatch.delenv('ALEX_DISCOVERY_SYNC', raising=False)
    monkeypatch.delenv('ALEX_CLASSIFICATION_SYNC', raising=False)
    jobs = [job for job in source['jobs'].values() if any(
        'python -m alex.cli classify' in step.get('run', '') for step in job['steps'])]
    assert len(jobs) == 1
    job = jobs[0]
    step = next(step for step in job['steps'] if
                'python -m alex.cli classify' in step.get('run', ''))
    env = {**source.get('env', {}), **job.get('env', {}), **step.get('env', {})}
    for name in ('ALEX_DISCOVERY_SYNC', 'ALEX_CLASSIFICATION_SYNC'):
        if name in env:
            monkeypatch.setenv(name, str(env[name]))
    publish = Mock(side_effect=subprocess.CalledProcessError(1, ['state.sh', 'push']))
    monkeypatch.setattr('alex.utils.paid_classification.subprocess.run', publish)
    send = Mock(return_value=VALID)
    body = {'input': 'new paid work'}
    with pytest.raises(PaidRequestHeld, match='sync'):
        ledger = Ledger(tmp_path, [digest(body)])
        ledger.perform(body, send, lambda value: value)
    publish.assert_called_once()
    send.assert_not_called()
    assert any(s.get('if') == 'always()' and
               s.get('with', {}).get('path') == 'data/classification_request_ledger.json'
               for s in job['steps'])

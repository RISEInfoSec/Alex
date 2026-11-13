"""Recovery tests use mock HTTP only; never contact an upstream API."""
import json
from unittest.mock import MagicMock

import pytest
import requests

from alex.connectors import openalex
from alex.utils import http
from alex.utils.discovery_checkpoint import DiscoveryClient, DiscoveryDeferred, DiscoveryIncomplete


@pytest.fixture
def setup(tmp_path, monkeypatch):
    monkeypatch.setattr(http, 'CACHE', tmp_path / 'cache.json')
    monkeypatch.setattr(http, '_openalex_policy', lambda: {
        'requests_enabled': True, 'min_interval_seconds': 60, 'request_timeout_seconds': 20,
        'failure_cooldown_seconds': 3600, 'retry_not_before': None})
    monkeypatch.setattr(http.time, 'sleep', lambda _: None)
    monkeypatch.delenv('ALEX_DISCOVERY_SYNC', raising=False)
    monkeypatch.delenv('ALEX_OPENALEX_STATE_PATH', raising=False)
    # An accidental unmocked request is an immediate test failure.
    monkeypatch.setattr(requests.Session, 'get', lambda *a, **kw: pytest.fail('Live HTTP forbidden'))
    return tmp_path


def response(status=200, body=None, headers=None):
    r = MagicMock()
    r.status_code = status
    r.headers = headers or {}
    r.json.return_value = body if body is not None else {'results': []}
    if status >= 400:
        r.raise_for_status.side_effect = requests.HTTPError(str(status))
    return r


def client(path, **budgets):
    return DiscoveryClient(path / 'checkpoint.json',
        {'from_date': '2026-10-26', 'until_date': '2026-11-02'},
        {'queries': ['osint']}, budgets)


@pytest.mark.parametrize('failure', [429, 503, 403, 'disconnect'])
def test_cooldown_stops_singletons_and_search_but_crossref_continues(setup, failure):
    c = client(setup)
    c.session.get = MagicMock(side_effect=[requests.ConnectionError('broken') if failure == 'disconnect'
        else response(failure, headers={'Retry-After': '7200'}), response()])
    c.run_task('OpenAlex:q', lambda: openalex.search(c, 'q'))
    c.run_task('OpenAlex:dois', lambda: openalex.get_many_by_doi(c, ['10.1/a', '10.1/b']))
    c.run_task('Crossref:q', lambda: c.get_json('https://api.crossref.org/works'))
    assert c.openalex_count == 1
    assert c.session.get.call_count == 2
    assert len(c.failures) == 2
    with pytest.raises(DiscoveryIncomplete):
        c.finish(setup / 'receipt.json', 0)
    report = json.loads((setup / 'receipt.json').read_text())
    assert report['status'] == 'partial'
    assert report['actual_request_count'] == 2


def test_request_budget_counts_network_not_replay(setup):
    c = client(setup, max_requests=1)
    c.session.get = MagicMock(return_value=response(body={'results': [1]}))
    url = 'https://api.crossref.org/works'
    assert c.get_json(url) == {'results': [1]}
    assert c.get_json(url) == {'results': [1]}
    with pytest.raises(DiscoveryDeferred, match='request_budget'):
        c.get_json(url, params={'page': 2})
    assert c.session.get.call_count == 1


def test_openalex_budget_shared_by_doi_and_search(setup):
    c = client(setup, openalex_max_requests=1)
    c.session.get = MagicMock(return_value=response(body={'ids': {'doi': 'https://doi.org/10.1/a'}}))
    assert openalex.get_by_doi(c, '10.1/a')
    with pytest.raises(DiscoveryDeferred, match='openalex_request_budget'):
        openalex.search(c, 'osint')
    assert c.session.get.call_count == 1


def test_shared_run_budget_is_distinct_and_preserves_checkpoint(setup, monkeypatch):
    monkeypatch.setenv('GITHUB_RUN_ID', 'weekly-run')
    state_path = setup / 'cache.json.openalex-policy'
    original_state = {'request_attempts_by_run': {'weekly-run': 249}, 'retry_not_before': 0}
    state_path.write_text(json.dumps(original_state))
    c = client(setup, openalex_max_requests=250)
    c.run_task('Crossref:completed', lambda: ['retained'])
    c.session.get = MagicMock(return_value=response(body={'ids': {'doi': 'https://doi.org/10.1/a'}}))
    c.run_task('OpenAlex:bulk', lambda: openalex.get_many_by_doi(c, ['10.1/a', '10.1/b']))
    assert c.failures['OpenAlex:bulk'] == 'openalex_run_request_budget'
    assert c.session.get.call_count == 1
    assert c.openalex_deferred()
    with pytest.raises(DiscoveryDeferred, match='openalex_run_request_budget'):
        c.on_openalex_deferred()
    with pytest.raises(DiscoveryDeferred, match='openalex_run_request_budget'):
        c.get_json('https://api.openalex.org/works', params={'q': 'new'})
    c.run_task('OpenAlex:later', lambda: pytest.fail('must not send'))
    assert c.failures['OpenAlex:later'] == 'openalex_run_request_budget'
    c.run_task('Crossref:independent', lambda: ['independent'])
    with pytest.raises(DiscoveryIncomplete):
        c.finish(setup / 'receipt.json', 0)
    receipt = json.loads((setup / 'receipt.json').read_text())
    assert receipt['status'] == 'partial'
    assert receipt['actual_request_count'] == receipt['openalex_request_count'] == 1
    assert receipt['window'] == {'from_date': '2026-10-26', 'until_date': '2026-11-02'}
    assert c.state['tasks']['Crossref:completed'] == ['retained']
    assert c.state['tasks']['Crossref:independent'] == ['independent']
    assert len(c.state['responses']) == 1
    assert json.loads(state_path.read_text())['request_attempts_by_run']['weekly-run'] == 250

    # A GitHub retry has the same run ID and cannot replenish the run budget.
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT', '2')
    retry = client(setup, openalex_max_requests=250)
    retry.session.get = MagicMock()
    retry.run_task('OpenAlex:later', lambda: openalex.search(retry, 'new'))
    retry.session.get.assert_not_called()
    assert retry.failures['OpenAlex:later'] == 'openalex_run_request_budget'


def test_real_cooldown_is_not_mislabelled_as_run_budget(setup, monkeypatch):
    monkeypatch.setenv('GITHUB_RUN_ID', 'weekly-run')
    state_path = setup / 'cache.json.openalex-policy'
    state_path.write_text(json.dumps({'request_attempts_by_run': {'weekly-run': 249}}))
    c = client(setup, openalex_max_requests=250)
    c.session.get = MagicMock(return_value=response(429, headers={'Retry-After': '7200'}))
    c.run_task('OpenAlex:q', lambda: openalex.search(c, 'q'))
    c.run_task('OpenAlex:later', lambda: openalex.search(c, 'other'))
    assert set(c.failures.values()) == {'openalex_cooldown'}
    assert c.session.get.call_count == 1
    state = json.loads(state_path.read_text())
    assert state['request_attempts_by_run']['weekly-run'] == 250
    assert state['last_failure'] == 'HTTP429'
    assert state['retry_not_before'] > http.time.time()


def test_active_provider_hold_takes_precedence_over_exhausted_run_budget(setup, monkeypatch):
    monkeypatch.setenv('GITHUB_RUN_ID', 'weekly-run')
    state_path = setup / 'cache.json.openalex-policy'
    original = {'request_attempts_by_run': {'weekly-run': 250},
                'last_failure': 'HTTP429', 'retry_not_before': http.time.time() + 7200}
    state_path.write_text(json.dumps(original))
    c = client(setup, openalex_max_requests=250)
    c.session.get = MagicMock()
    c.run_task('OpenAlex:q', lambda: openalex.search(c, 'q'))
    assert c.failures['OpenAlex:q'] == 'openalex_cooldown'
    c.session.get.assert_not_called()
    assert json.loads(state_path.read_text()) == original


def test_single_pass_250_cap_followed_by_shared_run_cap_sends_nothing_more(setup, monkeypatch):
    monkeypatch.setenv('GITHUB_RUN_ID', 'weekly-run')
    monkeypatch.setattr(http, '_openalex_policy', lambda: {
        'requests_enabled': True, 'min_interval_seconds': 0,
        'request_timeout_seconds': 20, 'failure_cooldown_seconds': 3600,
        'retry_not_before': None, 'max_openalex_requests_per_run': 250})
    first = client(setup, max_requests=300, openalex_max_requests=250)
    first.session.get = MagicMock(return_value=response())
    for page in range(250):
        first.get_json('https://api.openalex.org/works', params={'page': page})
    with pytest.raises(DiscoveryDeferred, match='^openalex_request_budget$'):
        first.get_json('https://api.openalex.org/works', params={'page': 250})
    assert first.session.get.call_count == 250
    following = client(setup, max_requests=300, openalex_max_requests=250)
    following.session.get = MagicMock()
    following.run_task('OpenAlex:remaining', lambda: following.get_json(
        'https://api.openalex.org/works', params={'page': 250}))
    assert following.failures['OpenAlex:remaining'] == 'openalex_run_request_budget'
    following.session.get.assert_not_called()
    assert json.loads((setup / 'cache.json.openalex-policy').read_text())['request_attempts_by_run']['weekly-run'] == 250


def test_does_not_sleep_past_runtime_budget(setup, monkeypatch):
    c = client(setup, runtime_seconds=10)
    c.session.get = MagicMock()
    sleeps = []
    monkeypatch.setattr(http.time, 'sleep', sleeps.append)
    with pytest.raises(DiscoveryDeferred, match='runtime_budget'):
        openalex.search(c, 'q')  # 20-second request cannot fit.
    c.session.get.assert_not_called()
    assert all(n < 1 for n in sleeps)


def test_response_pages_and_tasks_resume_without_rechecking(setup):
    c = client(setup)
    c.session.get = MagicMock(side_effect=[response(body={'results': [{'id': 1}]}), response(503)])
    def pages(c):
        return [c.get_json('https://api.openalex.org/works', params={'page': p}) for p in (1, 2)]
    c.run_task('OpenAlex:q', lambda: pages(c))
    c.run_task('Crossref:done', lambda: [{'title': 'keep this'}])
    with pytest.raises(DiscoveryIncomplete):
        c.finish(setup / 'receipt.json', 1)
    # A later pass still respects the persisted provider cooldown.
    held = client(setup)
    held.session.get = MagicMock()
    held.run_task('OpenAlex:q', lambda: pages(held))
    held.session.get.assert_not_called()
    # Advance past cooldown: only page 2 is sent. Page 1 and the independent
    # completed task replay from durable checkpoint, with the original dates.
    monkey_state = setup / 'cache.json.openalex-policy'
    state = json.loads(monkey_state.read_text())
    state['retry_not_before'] = 0
    state['last_request_at'] = 0
    monkey_state.write_text(json.dumps(state))
    resumed = client(setup)
    resumed.session.get = MagicMock(return_value=response(body={'results': [{'id': 2}]}))
    assert resumed.run_task('Crossref:done', lambda: pytest.fail('must replay')) == [{'title': 'keep this'}]
    assert resumed.run_task('OpenAlex:q', lambda: pages(resumed))[0]['results'] == [{'id': 1}]
    assert resumed.session.get.call_count == 1
    assert resumed.session.get.call_args.kwargs['params']['page'] == 2
    assert resumed.finish(setup / 'receipt.json', 0)['status'] == 'complete'


def test_singleton_404_is_completed_missing_result_not_a_retry(setup):
    c = client(setup)
    c.session.get = MagicMock(return_value=response(404))
    assert c.run_task('OpenAlex:doi', lambda: openalex.get_by_doi(c, '10.1/missing')) is None
    c.run_task('OpenAlex:doi', lambda: pytest.fail('404 should be replayed'))
    assert c.session.get.call_count == 1
    assert c.finish(setup / 'receipt.json', 0)['status'] == 'complete'


def test_zero_quota_stops_next_singleton_and_records_safe_headers(setup, monkeypatch):
    monkeypatch.setenv('OPENALEX_API_KEY', 'DO_NOT_LEAK')
    c = client(setup)
    c.session.get = MagicMock(return_value=response(body={'ids': {'doi': 'https://doi.org/10.1/a'}},
        headers={'X-RateLimit-Remaining': '0', 'X-RateLimit-Reset': '3600',
                 'X-RateLimit-Credits-Used': '0', 'Authorization': 'DO_NOT_LEAK'}))
    assert c.run_task('OpenAlex:doi', lambda: openalex.get_many_by_doi(c, ['10.1/a', '10.1/b'])) == []
    assert c.openalex_count == 1
    with pytest.raises(DiscoveryIncomplete):
        c.finish(setup / 'receipt.json', 0)
    assert 'DO_NOT_LEAK' not in (setup / 'receipt.json').read_text()
    assert 'DO_NOT_LEAK' not in (setup / 'checkpoint.json').read_text()
    assert c.requests[0]['endpoint_type'] == 'singleton'
    assert c.requests[0]['quota']['X-RateLimit-Credits-Used'] == 0


def test_periodic_remote_state_sync_is_bounded_and_failure_stops_work(setup, monkeypatch):
    c = client(setup)
    c.sync_enabled = True
    c.last_sync -= 121
    push = MagicMock()
    monkeypatch.setattr('alex.utils.discovery_checkpoint.subprocess.run', push)
    c.session.get = MagicMock(return_value=response())
    c.get_json('https://api.crossref.org/works')
    assert push.call_count == 1
    assert push.call_args.kwargs['timeout'] == 120
    c.sync(force=True)
    assert push.call_count == 2
    import subprocess
    push.side_effect = subprocess.CalledProcessError(1, 'state.sh')
    with pytest.raises(DiscoveryDeferred, match='state_sync_failed'):
        c.sync(force=True)
    with pytest.raises(DiscoveryDeferred, match='state_sync_failed'):
        c.get_json('https://api.crossref.org/works', params={'page': 2})
    assert c.session.get.call_count == 1


def test_resumed_discovery_preserves_candidates_and_enriches_new_arrivals(setup, monkeypatch):
    from alex.pipelines import discovery
    from alex.utils import io
    for name in ('ROOT', 'DATA_DIR', 'CONFIG_DIR'):
        monkeypatch.setattr(io, name, setup if name == 'ROOT' else setup / ('data' if name == 'DATA_DIR' else 'config'))
    (setup / 'config').mkdir()
    (setup / 'data').mkdir()
    registry = {'queries': ['q1', 'q2'], 'connectors': {
        k: {'enabled': k == 'crossref'} for k in
        ('openalex', 'crossref', 'arxiv_rss', 'zenodo', 'github', 'core', 'semantic_scholar')}}
    (setup / 'config/query_registry.json').write_text(json.dumps(registry))
    def paper(letter):
        return {'title': ['OSINT paper ' + letter], 'DOI': '10.1/' + letter}
    search = MagicMock(side_effect=[[paper('a')], DiscoveryDeferred('runtime_budget')])
    monkeypatch.setattr(discovery.crossref, 'search', search)
    enrich = MagicMock(side_effect=lambda c, dois, mailto: {
        d: {'abstract_inverted_index': {'osint': [0]}} for d in dois})
    monkeypatch.setattr(discovery.openalex, 'get_many_by_doi', enrich)
    with pytest.raises(DiscoveryIncomplete):
        discovery.run()
    import pandas as pd
    saved = pd.read_csv(setup / 'data/discovery_candidates.csv')
    assert list(saved['title']) == ['OSINT paper a']
    assert saved.iloc[0]['abstract'] == 'osint'
    assert json.loads((setup / 'data/discovery_run_receipt.json').read_text())['status'] == 'partial'
    search.side_effect = [[paper('b')]]
    discovery.run()
    saved = pd.read_csv(setup / 'data/discovery_candidates.csv')
    assert list(saved['title']) == ['OSINT paper a', 'OSINT paper b']
    assert list(saved['abstract']) == ['osint', 'osint']
    assert search.call_count == 3  # q1 was not searched twice.
    assert enrich.call_args.args[1] == ['10.1/b']
    assert json.loads((setup / 'data/discovery_run_receipt.json').read_text())['status'] == 'complete'


def test_corrupt_checkpoint_fails_closed(setup):
    (setup / 'checkpoint.json').write_text('{broken')
    with pytest.raises(json.JSONDecodeError):
        client(setup)


def test_discovery_preserves_declared_zenodo_types_and_crossref_types(setup, monkeypatch):
    from alex.pipelines import discovery
    from alex.utils import io
    import pandas as pd
    monkeypatch.setattr(io, 'ROOT', setup)
    (setup/'config').mkdir();(setup/'data').mkdir()
    registry={'queries':['cybercrime'],'connectors':{k:{'enabled':k in ('crossref','zenodo')} for k in ('openalex','crossref','arxiv_rss','zenodo','github','core','semantic_scholar')}}
    (setup/'config/query_registry.json').write_text(json.dumps(registry))
    monkeypatch.setattr(discovery.crossref,'search',lambda *a,**k:[{'title':['Cybercrime journal paper'],'type':'journal-article','DOI':'10.1/paper'}])
    monkeypatch.setattr(discovery.zenodo,'search',lambda *a,**k:[{'metadata':{'title':'Cybercrime observations','resource_type':{'type':'dataset'},'doi':'10.1/data'}},{'metadata':{'title':'Cybercrime technical report','resource_type':{'type':'publication','subtype':'report'},'doi':'10.1/report'}}])
    monkeypatch.setattr(discovery.openalex,'get_many_by_doi',lambda *a,**k:{})
    discovery.run()
    rows=pd.read_csv(setup/'data/discovery_candidates.csv',keep_default_na=False).set_index('doi')
    assert rows.loc['10.1/paper','discovery_resource_type']=='journal-article'
    assert rows.loc['10.1/data','discovery_resource_type']=='dataset'
    assert rows.loc['10.1/report','discovery_resource_subtype']=='report'


def test_other_source_failure_is_not_mislabelled_openalex_cooldown(setup):
    c = client(setup)
    c._openalex_hold = True
    c.session.get = MagicMock(return_value=response(503))
    c.run_task('Crossref:q', lambda: c.get_json('https://api.crossref.org/works'))
    assert c.failures['Crossref:q'] == 'request_failed'
    assert c.session.get.call_count == 3


def test_invalid_arxiv_xml_is_failed_coverage_not_an_empty_success(setup):
    c = client(setup)
    r = response()
    r.text = '<broken'
    c.session.get = MagicMock(return_value=r)
    c.run_task('arXiv:q', lambda: c.get_raw('http://export.arxiv.org/api/query'))
    with pytest.raises(DiscoveryIncomplete):
        c.finish(setup / 'receipt.json', 0)
    report = json.loads((setup / 'receipt.json').read_text())
    assert report['status'] == 'failed'
    assert report['deferred_tasks']['arXiv:q'] == 'invalid_xml_response'


def test_discovery_uses_only_durable_cache_and_replays_after_restart(setup):
    legacy=setup/'cache.json'
    legacy.write_text(json.dumps({'obsolete':None,'unrelated':{'value':'preserve'}}))
    original=legacy.read_bytes()
    c=client(setup)
    c.session.get=MagicMock(return_value=response(body={'results':[{'title':'Retained source result'}]}))
    url='https://api.crossref.org/works'
    value=c.get_json(url)
    assert c.session.get.call_count==1 and legacy.read_bytes()==original
    checkpoint=json.loads((setup/'checkpoint.json').read_text())
    assert list(checkpoint['responses'].values())==[value]
    assert len(checkpoint['last_attempt_requests'])==1
    assert checkpoint['last_attempt_requests'][0]['http_status']==200
    resumed=client(setup)
    resumed.session.get=MagicMock(side_effect=AssertionError('Completed response must not be fetched again'))
    assert resumed.get_json(url)==value
    resumed.session.get.assert_not_called()
    assert resumed.requests==[] and legacy.read_bytes()==original

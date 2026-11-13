import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock
import pytest,requests
from alex.utils import http

@pytest.fixture
def setup(tmp_path,monkeypatch):
 monkeypatch.setattr(http,'CACHE',tmp_path/'cache.json')
 monkeypatch.setattr(http,'_shared_coordinator_unavailable',lambda:False)
 monkeypatch.setattr(http,'_openalex_policy',lambda:{'requests_enabled':True,'min_interval_seconds':60,'request_timeout_seconds':20,'failure_cooldown_seconds':3600,'retry_not_before':None})
 monkeypatch.setattr(http.time,'sleep',lambda n:None)
 return tmp_path

def response(status=200,headers=None):
 r=MagicMock();r.status_code=status;r.headers=headers or {};r.json.return_value={'ok':True}
 if status>=400:r.raise_for_status.side_effect=requests.HTTPError(str(status))
 return r

def test_pacing_shared_across_clients_and_cache_hits_do_not_request(setup,monkeypatch):
 slept=[];monkeypatch.setattr(http.time,'sleep',slept.append);monkeypatch.setattr(http.time,'time',lambda:10000)
 a,b=http.HttpClient(),http.HttpClient();a.session.get=MagicMock(return_value=response());b.session.get=MagicMock(return_value=response())
 assert a.get_json('https://api.openalex.org/works',params={'q':'a'})=={'ok':True}
 assert a.get_json('https://api.openalex.org/works',params={'q':'a'})=={'ok':True}
 b.get_json('https://api.openalex.org/works',params={'q':'b'})
 assert a.session.get.call_count==1 and b.session.get.call_count==1 and 60 in slept
 assert a.session.get.call_args.kwargs['timeout']==20

def test_request_budget_is_shared_across_clients_and_preserved_for_run(setup,monkeypatch):
 monkeypatch.setenv('GITHUB_RUN_ID','123456')
 monkeypatch.setattr(http,'_openalex_policy',lambda:{'requests_enabled':True,'min_interval_seconds':0,
  'request_timeout_seconds':20,'failure_cooldown_seconds':3600,'retry_not_before':None,'max_openalex_requests_per_run':2})
 first,second=http.HttpClient(),http.HttpClient()
 first.session.get=MagicMock(return_value=response());second.session.get=MagicMock(return_value=response())
 assert first.get_json('https://api.openalex.org/works',params={'q':'one'})=={'ok':True}
 assert second.get_json('https://api.openalex.org/works',params={'q':'two'})=={'ok':True}
 third=http.HttpClient();third.session.get=MagicMock(return_value=response())
 assert third.get_json('https://api.openalex.org/works',params={'q':'three'}) is None
 third.session.get.assert_not_called()
 assert json.loads((setup/'cache.json.openalex-policy').read_text())['request_attempts_by_run']['123456']==2
 monkeypatch.setenv('GITHUB_RUN_ID','123457')
 next_run=http.HttpClient();next_run.session.get=MagicMock(return_value=response())
 assert next_run.get_json('https://api.openalex.org/works',params={'q':'next'})=={'ok':True}

def test_invalid_budget_checkpoint_fails_closed_before_network(setup,monkeypatch):
 monkeypatch.setenv('GITHUB_RUN_ID','123456')
 (setup/'cache.json.openalex-policy').write_text(json.dumps({'request_attempts_by_run':{'123456':'corrupt'}}))
 client=http.HttpClient();client.session.get=MagicMock(return_value=response())
 assert client.get_json('https://api.openalex.org/works') is None
 client.session.get.assert_not_called()

@pytest.mark.parametrize('hold',[{'owner_pause':{'reason':'owner'}},{'reconciliation_hold':{'http_status':429}}])
def test_policy_hold_overrides_enabled_flag_before_network(setup,monkeypatch,hold):
 monkeypatch.setattr(http,'_openalex_policy',lambda:{'requests_enabled':True,**hold})
 client=http.HttpClient();client.session.get=MagicMock(return_value=response())
 assert client.get_json('https://api.openalex.org/works') is None
 client.session.get.assert_not_called()

@pytest.mark.parametrize('policy',[{}, {'requests_enabled':None}, {'requests_enabled':1}, None, []])
def test_missing_or_invalid_enabled_flag_never_authorizes_a_send(setup,monkeypatch,policy):
 monkeypatch.setattr(http,'_openalex_policy',lambda:policy)
 client=http.HttpClient();client.session.get=MagicMock(side_effect=AssertionError('provider request forbidden'))
 assert client.get_json('https://api.openalex.org/works') is None
 assert client.openalex_deferred();client.session.get.assert_not_called()

def test_policy_change_during_pacing_stops_before_reservation_or_send(setup,monkeypatch):
 monkeypatch.setattr(http.time,'time',lambda:10000)
 state={'last_request_at':10000,'request_attempts_by_run':{}}
 path=setup/'cache.json.openalex-policy';path.write_text(json.dumps(state))
 current={'requests_enabled':True,'min_interval_seconds':60,'request_timeout_seconds':20,
          'failure_cooldown_seconds':3600,'retry_not_before':None}
 monkeypatch.setattr(http,'_openalex_policy',lambda:dict(current))
 monkeypatch.setattr(http.time,'sleep',lambda _:current.update(requests_enabled=False))
 client=http.HttpClient();client.session.get=MagicMock(side_effect=AssertionError('provider request forbidden'))
 assert client.get_json('https://api.openalex.org/works') is None
 assert client.openalex_deferred();client.session.get.assert_not_called()
 assert json.loads(path.read_text())==state

@pytest.mark.parametrize('failure',[429,503,'timeout'])
def test_failure_stops_requests_and_cooldown_survives_new_client(setup,failure,monkeypatch):
 monkeypatch.setattr(http.time,'time',lambda:10000)
 a=http.HttpClient();a.session.get=MagicMock(side_effect=requests.Timeout() if failure=='timeout' else None,return_value=response(failure if isinstance(failure,int) else 200,{'Retry-After':'62010'}))
 assert a.get_json('https://api.openalex.org/works') is None
 assert a.session.get.call_count==1
 b=http.HttpClient();b.session.get=MagicMock(return_value=response())
 assert b.get_json('https://api.openalex.org/works',params={'different':'query'}) is None
 b.session.get.assert_not_called()
 b.get_json('https://api.crossref.org/works');assert b.session.get.call_count==1


def test_hold_deadline_prevents_even_first_request(setup,monkeypatch):
 monkeypatch.setattr(http,'_openalex_policy',lambda:{'requests_enabled':True,'min_interval_seconds':60,'request_timeout_seconds':20,'failure_cooldown_seconds':3600,'retry_not_before':'2999-01-01T00:00:00Z'})
 a=http.HttpClient();a.session.get=MagicMock();assert a.get_json('https://api.openalex.org/works') is None;a.session.get.assert_not_called()


def test_http_date_retry_after_is_parsed(monkeypatch):
 monkeypatch.setattr(http.time,'time',lambda:0)
 assert http.HttpClient._parse_retry_after('Thu, 01 Jan 1970 01:00:00 GMT')==3600

def test_concurrent_clients_never_overlap_openalex_calls(setup):
 import threading
 state={'active':0,'maximum':0};guard=threading.Lock()
 def get(*args,**kwargs):
  with guard:state['active']+=1;state['maximum']=max(state['maximum'],state['active'])
  threading.Event().wait(.01)
  with guard:state['active']-=1
  return response()
 clients=[http.HttpClient(),http.HttpClient()]
 for client in clients:client.session.get=MagicMock(side_effect=get)
 with ThreadPoolExecutor(max_workers=2) as pool:
  list(pool.map(lambda pair:pair[1].get_json('https://api.openalex.org/works',params={'query':str(pair[0])}),enumerate(clients)))
 assert state['maximum']==1


def test_waiting_thread_preserves_429_on_last_run_budgeted_request(setup, monkeypatch):
 import threading
 entered, waiting = threading.Event(), threading.Event()
 class ObservedLock:
  def __init__(self): self.lock = threading.Lock()
  def __enter__(self):
   if self.lock.locked(): waiting.set()
   self.lock.acquire()
  def __exit__(self, *args): self.lock.release()
 monkeypatch.setattr(http, '_OPENALEX_LOCK', ObservedLock())
 monkeypatch.setenv('GITHUB_RUN_ID', 'weekly-run')
 (setup/'cache.json.openalex-policy').write_text(json.dumps({'request_attempts_by_run': {'weekly-run': 249}}))
 client = http.HttpClient()
 def get(*args, **kwargs):
  entered.set()
  assert waiting.wait(3)
  return response(429, {'Retry-After': '7200'})
 client.session.get = MagicMock(side_effect=get)
 with ThreadPoolExecutor(max_workers=2) as pool:
  first = pool.submit(client.get_json, 'https://api.openalex.org/works', {'q':'one'})
  assert entered.wait(3)
  second = pool.submit(client.get_json, 'https://api.openalex.org/works', {'q':'two'})
  assert first.result(timeout=5) is None
  assert second.result(timeout=5) is None
 assert client.session.get.call_count == 1
 assert client.openalex_deferred_reason() == 'openalex_cooldown'
 state = json.loads((setup/'cache.json.openalex-policy').read_text())
 assert state['request_attempts_by_run']['weekly-run'] == 250
 assert state['last_failure'] == 'HTTP429'


def test_provider_evidence_survives_cooldown_and_later_success(setup, monkeypatch):
 now = [10000]
 monkeypatch.setattr(http.time, 'time', lambda: now[0])
 monkeypatch.setenv('OPENALEX_API_KEY', 'private-api-key')
 headers = {'Retry-After': '7200', 'X-RateLimit-Remaining': '0',
            'X-RateLimit-Reset': '8000', 'X-RateLimit-Limit': '10000',
            'X-RateLimit-Credits-Used': '10',
            'Date': 'Thu, 01 Jan 1970 02:46:40 GMT',
            'Set-Cookie': 'private-cookie', 'Authorization': 'private-api-key'}
 client = http.HttpClient()
 client.session.get = MagicMock(return_value=response(429, headers))
 assert client.get_json('https://api.openalex.org/works') is None
 path = setup / 'cache.json.openalex-policy'
 state = json.loads(path.read_text())
 failure = state['last_failure_response']
 assert failure['http_status'] == 429
 assert failure['headers'] == {key: value for key, value in headers.items()
                              if key not in ('Set-Cookie', 'Authorization')}
 assert failure['observed_at'] == '1970-01-01T02:46:40+00:00'
 assert state['retry_not_before'] == 18000
 assert 'private-' not in path.read_text()
 blocked = http.HttpClient()
 blocked.session.get = MagicMock()
 assert blocked.get_json('https://api.openalex.org/works') is None
 blocked.session.get.assert_not_called()
 # A later permitted response updates current allowance, retaining the failure.
 now[0] = 18001
 resumed = http.HttpClient()
 resumed.session.get = MagicMock(return_value=response(200, {'X-RateLimit-Remaining': '9000'}))
 assert resumed.get_json('https://api.openalex.org/works') == {'ok': True}
 state = json.loads(path.read_text())
 assert state['last_response']['http_status'] == 200
 assert state['last_response']['headers'] == {'X-RateLimit-Remaining': '9000'}
 assert state['last_failure_response'] == failure
 assert client.session.get.call_count == resumed.session.get.call_count == 1


def test_evidence_does_not_copy_arbitrary_or_malformed_header_values():
 evidence = http._openalex_response_evidence(response(429, {
     'Retry-After': 'Bearer secret', 'Date': 'bad\r\nsecret',
     'X-RateLimit-Remaining': 'NaN', 'X-RateLimit-Limit': '1' * 129,
     'X-RateLimit-Reset': 'Infinity', 'Authorization': 'private-key'}))
 assert evidence['headers'] == {}
 assert len(evidence['invalid_header_names']) == 5
 assert 'secret' not in json.dumps(evidence) and 'private-key' not in json.dumps(evidence)


def test_http_date_evidence_is_retained_verbatim():
 value = 'Thu, 01 Jan 1970 03:00:00 GMT'
 evidence = http._openalex_response_evidence(response(429, {'Retry-After': value}))
 assert evidence['headers'] == {'Retry-After': value}
 assert http._openalex_response_evidence(response(429, {
     'Retry-After': value + ' private-token'}))['headers'] == {}

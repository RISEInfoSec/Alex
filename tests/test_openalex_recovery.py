import json
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import MagicMock
import pytest,requests
from alex.utils import http

@pytest.fixture
def setup(tmp_path,monkeypatch):
 monkeypatch.setattr(http,'CACHE',tmp_path/'cache.json')
 monkeypatch.setattr(http,'_openalex_policy',lambda:{'min_interval_seconds':60,'request_timeout_seconds':20,'failure_cooldown_seconds':3600,'retry_not_before':None})
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
 monkeypatch.setattr(http,'_openalex_policy',lambda:{'min_interval_seconds':60,'request_timeout_seconds':20,'failure_cooldown_seconds':3600,'retry_not_before':'2999-01-01T00:00:00Z'})
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

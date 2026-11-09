import pandas as pd
import pytest
import requests
from unittest.mock import Mock, patch
from alex.pipelines import citation_chain

@pytest.fixture(autouse=True)
def isolate_http(tmp_path, monkeypatch):
    monkeypatch.setattr('alex.utils.http.CACHE',tmp_path/'legacy.json')
    monkeypatch.setattr('alex.utils.http.time.sleep',lambda _:None)


def test_provider_hold_does_not_rewrite_candidates(tmp_path):
    data=tmp_path/'data'; data.mkdir()
    path=data/'discovery_candidates.csv'
    pd.DataFrame([{'title':'Synthetic seed','citation_count':1}]).to_csv(path,index=False)
    before=path.read_bytes()
    with patch('alex.utils.io.ROOT',tmp_path), patch('alex.pipelines.citation_chain.connector_config.load',return_value={}), patch('alex.utils.http._openalex_policy',return_value={'requests_enabled':False}), patch('alex.utils.http.HttpClient._send_request',side_effect=AssertionError('network forbidden')):
        with pytest.raises(citation_chain.CitationIncomplete,match='no output promoted'):
            citation_chain.run()
    assert path.read_bytes()==before


def test_invalid_search_payload_fails_but_empty_list_succeeds():
    response=Mock(status_code=200); response.json.return_value={}
    with patch.object(citation_chain.BaseHttpClient,'_request_with_retry',return_value=response):
        client=citation_chain.HttpClient()
        with pytest.raises(citation_chain.CitationIncomplete,match='invalid'):
            client.get_json('https://api.openalex.org/works')
        response.json.return_value={'results':[]}
        other=citation_chain.HttpClient()
        # The failed client cached a malformed response; use an independent cache.
        other.cache.clear()
        assert other.get_json('https://api.openalex.org/works') == {'results':[]}


def test_interrupted_candidate_write_preserves_previous_csv(tmp_path,monkeypatch):
    output=tmp_path/'discovery_candidates.csv';output.write_bytes(b'previous output\\n')
    def interrupted(_frame, stream, **_kwargs):
        stream.write('partial')
        raise OSError('synthetic interruption')
    monkeypatch.setattr(pd.DataFrame,'to_csv',interrupted)
    with pytest.raises(OSError): citation_chain._stage_complete_candidates(output,pd.DataFrame([{'title':'Synthetic'}]))
    assert output.read_bytes()==b'previous output\\n'
    assert not list(tmp_path.glob('.citation-*.tmp'))


def test_missing_single_s2_paper_is_not_provider_failure():
    client=citation_chain.HttpClient()
    response=Mock(status_code=404)
    response.raise_for_status.side_effect=requests.HTTPError('not found')
    with patch.object(citation_chain.BaseHttpClient,'_request_with_retry',return_value=response):
        assert client.get_json('https://api.semanticscholar.org/graph/v1/paper/synthetic') is None


def test_legacy_cache_is_not_read_or_changed_and_hold_fails(tmp_path, monkeypatch):
    import json
    from alex.utils import http
    path=tmp_path/'legacy.json'
    key=json.dumps({'url':'https://api.openalex.org/works','params':{},'headers':{}},sort_keys=True)
    path.write_text(json.dumps({key:{'results':[]}}));before=path.read_bytes()
    monkeypatch.setattr(http,'CACHE',path)
    with patch('alex.utils.http._openalex_policy',return_value={'requests_enabled':False}), patch('alex.utils.http.HttpClient._send_request',side_effect=AssertionError('network forbidden')):
        with pytest.raises(citation_chain.CitationIncomplete):
            citation_chain.HttpClient().get_json('https://api.openalex.org/works')
    assert path.read_bytes()==before


def test_citation_key_is_never_written_to_legacy_cache(tmp_path,monkeypatch):
    from alex.utils import http
    path=tmp_path/'legacy.json';path.write_text('{"preserved":{}}');before=path.read_bytes()
    monkeypatch.setattr(http,'CACHE',path)
    response=Mock(status_code=200);response.json.return_value={'data':[]}
    client=citation_chain.HttpClient()
    with patch.object(citation_chain.BaseHttpClient,'_request_with_retry',return_value=response):
        client.get_json('https://api.semanticscholar.org/graph/v1/paper/search',params={'query':'synthetic'},headers={'x-api-key':'SYNTHETIC_SECRET'})
    assert path.read_bytes()==before
    assert b'SYNTHETIC_SECRET' not in path.read_bytes()


def test_later_exception_stops_queued_work_before_first_completes(tmp_path,monkeypatch):
    import threading
    data=tmp_path/'data';data.mkdir();path=data/'discovery_candidates.csv'
    pd.DataFrame([{'title':f'Synthetic {i}','citation_count':3-i} for i in range(3)]).to_csv(path,index=False)
    first=threading.Event();second_failed=threading.Event();stopped=threading.Event();release=threading.Event();started=[]
    original_stop=citation_chain.HttpClient.stop
    def stop(client):
        original_stop(client);stopped.set()
    monkeypatch.setattr(citation_chain.HttpClient,'stop',stop)
    def work(_client,title,*_args):
        started.append(title)
        if title=='Synthetic 0':
            first.set();assert release.wait(4)
        elif title=='Synthetic 1':
            assert first.wait(4);second_failed.set();raise ValueError('synthetic')
        return []
    monkeypatch.setattr(citation_chain,'CITATION_CHAIN_WORKERS',2)
    errors=[]
    def run():
        try: citation_chain.run()
        except Exception as exc: errors.append(exc)
    with patch('alex.utils.io.ROOT',tmp_path), patch('alex.pipelines.citation_chain.connector_config.load',return_value={}),patch('alex.pipelines.citation_chain._chain_one_candidate',side_effect=work):
        t=threading.Thread(target=run);t.start()
        assert second_failed.wait(4)
        assert stopped.wait(4)
        release.set();t.join(4)
    assert not t.is_alive()
    assert len(errors)==1 and isinstance(errors[0],citation_chain.CitationIncomplete)
    assert 'Synthetic 2' not in started


def test_completed_response_is_retained_without_credentials(tmp_path,monkeypatch):
    import hashlib,json
    path=tmp_path/'evidence.jsonl'
    response=Mock(status_code=200);response.json.return_value={'data':[{'title':'Synthetic result'}]}
    client=citation_chain.HttpClient(evidence_path=path,evidence_context={'input_sha256':'1'*64})
    with patch.object(citation_chain.BaseHttpClient,'_request_with_retry',return_value=response):
        assert client.get_json('https://api.semanticscholar.org/graph/v1/paper/search',params={'query':'synthetic'},headers={'x-api-key':'SYNTHETIC_SECRET'}) == {'data':[{'title':'Synthetic result'}]}
    client.finish(complete=False)
    text=path.read_text();records=[json.loads(line) for line in text.splitlines()]
    assert 'SYNTHETIC_SECRET' not in text
    assert records[0]['replay_allowed'] is False and records[0]['context']['input_sha256']=='1'*64
    assert records[1]['event']=='response' and records[1]['response']=={'data':[{'title':'Synthetic result'}]}
    assert records[-1]['event']=='incomplete'


def test_response_containing_credential_is_not_written(tmp_path):
    path=tmp_path/'evidence.jsonl';client=citation_chain.HttpClient(evidence_path=path)
    response=Mock(status_code=200);response.json.return_value={'data':[{'title':'SYNTHETIC_SECRET'}]}
    with patch.object(citation_chain.BaseHttpClient,'_request_with_retry',return_value=response):
        with pytest.raises(citation_chain.CitationIncomplete,match='safely'):
            client.get_json('https://api.semanticscholar.org/graph/v1/paper/search',headers={'x-api-key':'SYNTHETIC_SECRET'})
    assert 'SYNTHETIC_SECRET' not in path.read_text()


def test_inflight_response_is_retained_after_stop(tmp_path):
    import json,threading
    from concurrent.futures import ThreadPoolExecutor
    entered,release=threading.Event(),threading.Event()
    response=Mock(status_code=200);response.json.return_value={'data':[{'title':'Synthetic'}]}
    path=tmp_path/'citation-evidence.jsonl'
    client=citation_chain.HttpClient(evidence_path=path,evidence_context={'input_sha256':'1'*64})
    def send(*_args,**_kwargs):
        entered.set();assert release.wait(4);return response
    client.session.get=Mock(side_effect=send)
    with ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(client.get_json,'https://api.semanticscholar.org/graph/v1/paper/search',{'query':'synthetic'},{'x-api-key':'SYNTHETIC_SECRET'})
        assert entered.wait(4);client.stop();release.set()
        assert pending.result()=={'data':[{'title':'Synthetic'}]}
    client.finish(complete=False)
    records=[json.loads(line) for line in path.read_text().splitlines()]
    assert any(r.get('response')=={'data':[{'title':'Synthetic'}]} for r in records)
    assert 'SYNTHETIC_SECRET' not in path.read_text()
    assert records[-1]['event']=='incomplete'

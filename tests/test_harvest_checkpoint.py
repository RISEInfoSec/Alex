import json
import shutil
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock

import pytest
import requests

from alex.utils.harvest_checkpoint import HarvestClient, HarvestCheckpointError


@pytest.fixture(autouse=True)
def isolated_http(tmp_path, monkeypatch):
    monkeypatch.setattr('alex.utils.http.CACHE', tmp_path / 'legacy.json')
    monkeypatch.setattr('alex.utils.http.time.sleep', lambda _:None)
    monkeypatch.delenv('ALEX_DISCOVERY_SYNC', raising=False)
    monkeypatch.delenv('ALEX_HARVEST_SYNC', raising=False)


def response(value):
    result = Mock(status_code=200)
    result.json.return_value = value
    return result


def test_new_runner_refuses_unfinished_checkpoint_before_sending(tmp_path):
    path = tmp_path/'runner1/data/harvest_response_cache.jsonl'
    remote = tmp_path/'remote.jsonl'
    first = HarvestClient(path, '1'*64, publish=lambda:shutil.copyfile(path,remote))
    first.session.get = Mock(return_value=response({'message':{'DOI':'10.1/one'}}))
    first.get_json('https://api.crossref.org/works/one')
    first.finish(complete=False)
    second_path = tmp_path/'runner2/data/harvest_response_cache.jsonl'
    second_path.parent.mkdir(parents=True)
    shutil.copyfile(remote,second_path)
    before=second_path.read_bytes()
    with pytest.raises(HarvestCheckpointError,match='Unfinished harvest checkpoint'):
        HarvestClient(second_path,'1'*64)
    assert second_path.read_bytes()==before


def test_legacy_cache_ignored_and_never_rewritten(tmp_path):
    legacy = tmp_path/'legacy.json'
    legacy.write_text(json.dumps({'stale':None}))
    before = legacy.read_bytes()
    client = HarvestClient(tmp_path/'data/harvest_response_cache.jsonl',('1'*64))
    client.session.get = Mock(return_value=response({'message':{'new':True}}))
    client.get_json('https://api.crossref.org/works/one')
    assert legacy.read_bytes() == before
    assert len(client.cache) == 1


def test_concurrent_duplicate_has_one_send(tmp_path):
    client = HarvestClient(tmp_path/'cache.jsonl',('1'*64))
    entered, release = threading.Event(), threading.Event()
    def send(*a,**k):
        entered.set()
        assert release.wait(3)
        return response({'message':{'ok':True}})
    client.session.get = Mock(side_effect=send)
    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(client.get_json,'https://api.crossref.org/works/one')
        assert entered.wait(3)
        two = pool.submit(client.get_json,'https://api.crossref.org/works/one')
        release.set()
        assert one.result() == two.result() == {'message':{'ok':True}}
    assert client.session.get.call_count == 1


def test_sync_failure_retains_response_and_blocks_next_send(tmp_path):
    path=tmp_path/'cache.jsonl'
    publish=Mock()
    client=HarvestClient(path,('1'*64),publish=publish)
    publish.side_effect=RuntimeError('conflicting writer')
    client.last_sync=-1000
    client.session.get=Mock(return_value=response({'message':{'ok':True}}))
    with pytest.raises(HarvestCheckpointError,match='sync failed'):
        client.get_json('https://api.crossref.org/works/one')
    with pytest.raises(HarvestCheckpointError):
        client.get_json('https://api.crossref.org/works/two')
    assert client.session.get.call_count==1
    assert any(json.loads(line).get('response') == {'message':{'ok':True}}
               for line in path.read_text().splitlines())
    with pytest.raises(HarvestCheckpointError,match='state uncertain'):
        HarvestClient(path,('1'*64))
    assert publish.call_count == 2  # Initial success and one failed attempt, no retry.


@pytest.mark.parametrize('fault',['truncated','hash','unknown'])
def test_corrupt_checkpoint_fails_before_requests(tmp_path,fault):
    path=tmp_path/'cache.jsonl'
    client=HarvestClient(path,('1'*64))
    client.session.get=Mock(return_value=response({'message':{'ok':True}}))
    client.get_json('https://api.crossref.org/works/one')
    if fault=='truncated':
        with path.open('a') as stream: stream.write('{')
    elif fault=='hash':
        path.write_text(path.read_text().replace('"ok":true','"ok":false'))
    else:
        with path.open('a') as stream: stream.write('{"event":"unknown"}\n')
    with pytest.raises(HarvestCheckpointError,match='Invalid harvest checkpoint'):
        HarvestClient(path,('1'*64))


def test_changed_input_requires_completion_and_retains_previous(tmp_path):
    path=tmp_path/'harvest_response_cache.jsonl'
    import hashlib
    output=tmp_path/'output.csv'; output.write_text('verified completed output')
    client=HarvestClient(path,('1'*64),output_path=output)
    with pytest.raises(HarvestCheckpointError,match='Unfinished harvest checkpoint'):
        HarvestClient(path,('2'*64),output_path=output)
    client.finish(complete=True,output_sha256=hashlib.sha256(output.read_bytes()).hexdigest())
    client.confirm_output()
    before=path.read_bytes()
    new=HarvestClient(path,('2'*64),output_path=output)
    assert path.with_name('harvest_response_cache_previous.jsonl').read_bytes()==before
    assert json.loads(path.read_text().splitlines()[0])['input_sha256']==('2'*64)
    assert not new.cache


def test_secret_headers_not_stored_and_changed_request_is_not_reused(tmp_path):
    path=tmp_path/'cache.jsonl'
    client=HarvestClient(path,('1'*64))
    client.session.get=Mock(return_value=response({'message':{'ok':True}}))
    client.get_json('https://api.crossref.org/works/one',headers={'x-api-key':'example-secret'})
    client.get_json('https://api.crossref.org/works/one',headers={'x-api-key':'another-secret'})
    assert client.session.get.call_count==2
    assert 'secret' not in path.read_text()
    assert 'x-api-key' not in path.read_text()


def test_not_found_is_retained_without_fabricating_a_response(tmp_path):
    path=tmp_path/'cache.jsonl'
    client=HarvestClient(path,('1'*64))
    failed=Mock(status_code=404)
    failed.raise_for_status.side_effect=requests.HTTPError('not found')
    client.session.get=Mock(return_value=failed)
    assert client.get_json('https://api.crossref.org/works/missing') is None
    record=json.loads(path.read_text().splitlines()[-1])
    assert record['event']=='not_found' and record['http_status']==404
    assert 'response' not in record
    client.session.get=Mock(side_effect=AssertionError('known404 must not be sent again'))
    assert client.get_json('https://api.crossref.org/works/missing') is None
    assert client.cache_hits==1
    with pytest.raises(HarvestCheckpointError,match='Unfinished harvest checkpoint'):
        HarvestClient(path,('1'*64))


@pytest.mark.parametrize('status',[400,401,403,429,500])
def test_denials_and_other_failures_are_not_not_found(tmp_path,status):
    client=HarvestClient(tmp_path/'cache.jsonl',('1'*64))
    failed=Mock(status_code=status,headers={'Retry-After':'3600'})
    failed.raise_for_status.side_effect=requests.HTTPError('failed')
    client.session.get=Mock(return_value=failed)
    with pytest.raises(HarvestCheckpointError, match='Provider lookup incomplete'):
        client.get_json('https://api.crossref.org/works/failure')
    assert not client.cache


def test_not_found_evidence_is_integrity_checked(tmp_path):
    path=tmp_path/'cache.jsonl'
    client=HarvestClient(path,('1'*64))
    client._cache_not_found('request-key',{'source':'native_log','job_id':1})
    path.write_text(path.read_text().replace('"http_status":404','"http_status":403'))
    with pytest.raises(HarvestCheckpointError,match='Invalid harvest checkpoint'):
        HarvestClient(path,('1'*64))


def test_local_fsync_failure_stops_next_request(tmp_path,monkeypatch):
    client=HarvestClient(tmp_path/'cache.jsonl',('1'*64))
    client.session.get=Mock(return_value=response({'message':{'ok':True}}))
    def fail(_): raise OSError('disk unavailable')
    monkeypatch.setattr('alex.utils.harvest_checkpoint.os.fsync',fail)
    with pytest.raises(HarvestCheckpointError,match='write failed'):
        client.get_json('https://api.crossref.org/works/one')
    with pytest.raises(HarvestCheckpointError):
        client.get_json('https://api.crossref.org/works/two')
    assert client.session.get.call_count==1


def test_json_null_is_not_persisted_as_success(tmp_path):
    path=tmp_path/'cache.jsonl'
    client=HarvestClient(path,('1'*64))
    client.session.get=Mock(return_value=response(None))
    with pytest.raises(HarvestCheckpointError, match='Provider lookup incomplete'):
        client.get_json('https://api.crossref.org/works/one')
    assert not client.cache
    with pytest.raises(HarvestCheckpointError,match='Unfinished harvest checkpoint'):
        HarvestClient(path,('1'*64))


def test_openalex_hold_fails_closed_without_sending(tmp_path, monkeypatch):
    monkeypatch.setattr('alex.utils.http._openalex_policy', lambda: {'requests_enabled': False})
    client = HarvestClient(tmp_path/'cache.jsonl', '1'*64)
    client.session.get = Mock(side_effect=AssertionError('no network permitted'))
    with pytest.raises(HarvestCheckpointError, match='Provider lookup incomplete'):
        client.get_json('https://api.openalex.org/works', params={'search':'synthetic'})
    with pytest.raises(HarvestCheckpointError, match='no further requests'):
        client.get_json('https://api.crossref.org/works/another')
    client.session.get.assert_not_called()
    client.finish(complete=False)
    assert '"event":"complete"' not in (tmp_path/'cache.jsonl').read_text()


def test_search_404_is_not_an_empty_success(tmp_path):
    client = HarvestClient(tmp_path/'cache.jsonl', '1'*64)
    failed = Mock(status_code=404)
    failed.raise_for_status.side_effect = requests.HTTPError('not found')
    client.session.get = Mock(return_value=failed)
    with pytest.raises(HarvestCheckpointError, match='Provider lookup incomplete'):
        client.get_json('https://api.semanticscholar.org/graph/v1/paper/search')


def test_inflight_success_is_retained_after_other_request_fails(tmp_path):
    path=tmp_path/'cache.jsonl'
    client=HarvestClient(path,'1'*64)
    entered, release = threading.Event(), threading.Event()
    def send(url, **_kwargs):
        if 'slow' in url:
            entered.set()
            assert release.wait(3)
            return response({'message': {'DOI':'synthetic'}})
        raise requests.ConnectionError('synthetic')
    client.session.get=Mock(side_effect=send)
    with ThreadPoolExecutor(max_workers=2) as pool:
        pending=pool.submit(client.get_json,'https://api.crossref.org/works/slow')
        assert entered.wait(3)
        with patch_openalex_denial():
            with pytest.raises(HarvestCheckpointError):
                client.get_json('https://api.openalex.org/works',params={'search':'synthetic'})
        release.set()
        assert pending.result() == {'message': {'DOI':'synthetic'}}
    client.finish(complete=False)
    assert any(json.loads(line).get('response') == {'message': {'DOI':'synthetic'}}
               for line in path.read_text().splitlines())
    with pytest.raises(HarvestCheckpointError,match='Unfinished harvest checkpoint'):
        HarvestClient(path,'1'*64)


def patch_openalex_denial():
    from unittest.mock import patch
    return patch('alex.utils.http._openalex_policy',return_value={'requests_enabled':False})


def test_malformed_success_is_not_retained_or_completed(tmp_path):
    path=tmp_path/'cache.jsonl'
    client=HarvestClient(path, '1'*64)
    client.session.get=Mock(return_value=response({}))
    with pytest.raises(HarvestCheckpointError,match='response invalid'):
        client.get_json('https://api.crossref.org/works/synthetic')
    client.finish(complete=False)
    assert not client.cache
    assert '"event":"complete"' not in path.read_text()


def test_stop_blocks_new_admission_but_waits_for_admitted_result(tmp_path):
    from alex.utils.http import HttpClient
    client=HarvestClient(tmp_path/'cache.jsonl','1'*64)
    entered,release=threading.Event(),threading.Event()
    def delayed(_self,_url,**_kwargs):
        entered.set();assert release.wait(3)
        return response({'message': {'DOI':'10.1/synthetic'}})
    from unittest.mock import patch
    with patch.object(HttpClient,'_send_request',delayed),ThreadPoolExecutor(max_workers=1) as pool:
        pending=pool.submit(client._send_request,'https://api.crossref.org/works/synthetic')
        assert entered.wait(3);client.stop()
        assert client.admitted_requests==1
        with pytest.raises(HarvestCheckpointError,match='no further requests'):
            client._send_request('https://api.crossref.org/works/other')
        release.set();assert pending.result().status_code==200
    assert client.admitted_requests==0


def test_final_sync_failure_keeps_guard_and_prior_output(tmp_path,monkeypatch):
    import hashlib
    import pandas as pd
    from unittest.mock import patch
    from alex.pipelines import harvest
    data=tmp_path/'data';data.mkdir()
    source=data/'accepted_candidates.csv';output=data/'accepted_harvested.csv'
    pd.DataFrame([{'title':'Synthetic','doi':'','authors':'','venue':'','abstract':'present'}]).to_csv(source,index=False)
    output.write_bytes(b'previous completed output\n')
    calls=[]
    def sync(_self):
        calls.append(1)
        if len(calls)==2: raise OSError('synthetic uncertain push')
    with patch('alex.utils.io.ROOT',tmp_path), patch('alex.pipelines.harvest.connector_config.load',return_value={}),patch.object(HarvestClient,'_publish',sync),patch('alex.pipelines.harvest._harvest_one',side_effect=lambda _client,row,*_args:row.to_dict()):
        with pytest.raises(HarvestCheckpointError,match='sync failed'):
            harvest.run()
    assert len(calls)==2
    assert output.read_bytes()==b'previous completed output\n'
    marker=data/'harvest_response_cache.jsonl.uncertain'
    assert marker.is_file()
    evidence=json.loads(marker.read_text())
    assert evidence['phase']=='completion'
    assert (data/evidence['staged_name']).is_file()
    assert (data/evidence['backup_name']).read_bytes()==output.read_bytes()
    with pytest.raises(HarvestCheckpointError,match='state uncertain'):
        HarvestClient(data/'harvest_response_cache.jsonl',hashlib.sha256(source.read_bytes()).hexdigest(),output_path=output)


def test_missing_or_changed_completed_output_requires_reconciliation(tmp_path):
    import hashlib
    output=tmp_path/'output.csv';output.write_bytes(b'verified output')
    path=tmp_path/'cache.jsonl'
    client=HarvestClient(path,'1'*64,output_path=output)
    client.finish(complete=True,output_sha256=hashlib.sha256(output.read_bytes()).hexdigest())
    client.confirm_output()
    output.write_bytes(b'different output')
    with pytest.raises(HarvestCheckpointError,match='output unverified'):
        HarvestClient(path,'2'*64,output_path=output)


def test_candidate_exception_stops_queued_harvest_before_first_finishes(tmp_path,monkeypatch):
    import pandas as pd
    from unittest.mock import patch
    from alex.pipelines import harvest
    data=tmp_path/'data';data.mkdir()
    pd.DataFrame([{'title':f'Synthetic {i}','doi':'','authors':'','venue':'','abstract':'present'} for i in range(3)]).to_csv(data/'accepted_candidates.csv',index=False)
    output=data/'accepted_harvested.csv';output.write_bytes(b'previous output\n')
    first,stopped,release=threading.Event(),threading.Event(),threading.Event();started=[]
    original_stop=HarvestClient.stop
    def stop(client): original_stop(client);stopped.set()
    def work(_client,row,*_args):
        title=row['title'];started.append(title)
        if title=='Synthetic 0': first.set();assert release.wait(4)
        elif title=='Synthetic 1': assert first.wait(4);raise ValueError('synthetic')
        return row.to_dict()
    monkeypatch.setattr(harvest,'HARVEST_WORKERS',2)
    monkeypatch.setattr(HarvestClient,'stop',stop)
    errors=[]
    def run():
        try: harvest.run()
        except Exception as exc: errors.append(exc)
    with patch('alex.utils.io.ROOT',tmp_path),patch('alex.pipelines.harvest.connector_config.load',return_value={}),patch('alex.pipelines.harvest._harvest_one',side_effect=work):
        t=threading.Thread(target=run);t.start();assert stopped.wait(4);release.set();t.join(4)
    assert not t.is_alive()
    assert len(errors)==1 and isinstance(errors[0],HarvestCheckpointError)
    assert 'Synthetic 2' not in started
    assert output.read_bytes()==b'previous output\n'


def test_state_sync_timeout_kills_group_and_reports_uncertainty(tmp_path,monkeypatch):
    import subprocess
    import signal
    from unittest.mock import patch
    client=HarvestClient(tmp_path/'data/cache.jsonl','1'*64,publish=lambda:None)
    monkeypatch.setenv('ALEX_HARVEST_SYNC','1')
    proc=Mock(pid=12345)
    proc.wait.side_effect=[subprocess.TimeoutExpired('state',120),0]
    with patch('alex.utils.harvest_checkpoint.subprocess.Popen',return_value=proc) as spawn,patch('alex.utils.harvest_checkpoint.os.killpg') as kill:
        with pytest.raises(HarvestCheckpointError,match='remote outcome and descendant cleanup unconfirmed'):
            client._publish()
    assert spawn.call_args.kwargs['start_new_session'] is True
    kill.assert_called_once_with(12345,signal.SIGKILL)
    assert proc.wait.call_count==2


def test_partial_append_marks_uncertain_and_blocks_next_attempt(tmp_path,monkeypatch):
    from pathlib import Path
    path=tmp_path/'cache.jsonl';client=HarvestClient(path,'1'*64,publish=lambda:None)
    original=Path.open
    class BrokenWriter:
        def __init__(self,stream): self.stream=stream
        def __enter__(self): return self
        def __exit__(self,*_args): self.stream.close()
        def write(self,text):
            self.stream.write(text[:12]);self.stream.flush()
            raise OSError('synthetic interrupted append')
    def injected(self,mode='r',*args,**kwargs):
        stream=original(self,mode,*args,**kwargs)
        return BrokenWriter(stream) if self==path and mode=='a' else stream
    monkeypatch.setattr(Path,'open',injected)
    with pytest.raises(HarvestCheckpointError,match='write failed'):
        client._cache_put('synthetic-key',{'message':{'DOI':'synthetic'}})
    monkeypatch.setattr(Path,'open',original)
    assert not path.read_bytes().endswith(b'\n')
    assert path.with_name(path.name+'.uncertain').is_file()
    with pytest.raises(HarvestCheckpointError,match='state uncertain'):
        HarvestClient(path,'1'*64,publish=lambda:None)


def test_fresh_runner_refuses_ambiguously_published_completion_without_output(tmp_path,monkeypatch):
    import hashlib
    import pandas as pd
    from unittest.mock import patch
    from alex.pipelines import harvest
    data=tmp_path/'runner'/'data';data.mkdir(parents=True)
    source=data/'accepted_candidates.csv';output=data/'accepted_harvested.csv'
    pd.DataFrame([{'title':'Synthetic','doi':'','authors':'','venue':'','abstract':'present'}]).to_csv(source,index=False)
    output.write_bytes(b'previous completed output\n')
    remote=tmp_path/'remote.jsonl';calls=[]
    def publish(client):
        calls.append(1);shutil.copyfile(client.path,remote)
        if len(calls)==2: raise OSError('synthetic lost acknowledgement')
    with patch('alex.utils.io.ROOT',tmp_path/'runner'),patch('alex.pipelines.harvest.connector_config.load',return_value={}),patch.object(HarvestClient,'_publish',publish),patch('alex.pipelines.harvest._harvest_one',side_effect=lambda _c,row,*_a:row.to_dict()):
        with pytest.raises(HarvestCheckpointError,match='sync failed'): harvest.run()
    assert len(calls)==2
    fresh=tmp_path/'fresh'/'data';fresh.mkdir(parents=True)
    shutil.copyfile(remote,fresh/'harvest_response_cache.jsonl')
    shutil.copyfile(output,fresh/'accepted_harvested.csv')
    with pytest.raises(HarvestCheckpointError,match='output unverified'):
        HarvestClient(fresh/'harvest_response_cache.jsonl',hashlib.sha256(source.read_bytes()).hexdigest(),publish=lambda:None,output_path=fresh/'accepted_harvested.csv')
    assert (fresh/'accepted_harvested.csv').read_bytes()==b'previous completed output\n'

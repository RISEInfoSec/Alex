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


def test_new_runner_reuses_exact_success_and_sends_only_missing(tmp_path, monkeypatch):
    path = tmp_path/'runner1/data/harvest_response_cache.jsonl'
    remote = tmp_path/'remote.jsonl'
    first = HarvestClient(path, ('1'*64), publish=lambda:shutil.copyfile(path,remote))
    first.session.get = Mock(return_value=response({'message':{'DOI':'10.1/one'}}))
    expected = first.get_json('https://api.crossref.org/works/one')
    first.finish(complete=False)
    second_path = tmp_path/'runner2/data/harvest_response_cache.jsonl'
    second_path.parent.mkdir(parents=True)
    shutil.copyfile(remote,second_path)
    second = HarvestClient(second_path, ('1'*64))
    second.session.get = Mock(return_value=response({'message':{'DOI':'10.1/two'}}))
    assert second.get_json('https://api.crossref.org/works/one') == expected
    second.get_json('https://api.crossref.org/works/two')
    assert second.session.get.call_count == 1
    assert second.session.get.call_args.args[0].endswith('/two')
    assert second.cache_hits == 1


def test_legacy_cache_ignored_and_never_rewritten(tmp_path):
    legacy = tmp_path/'legacy.json'
    legacy.write_text(json.dumps({'stale':None}))
    before = legacy.read_bytes()
    client = HarvestClient(tmp_path/'data/harvest_response_cache.jsonl',('1'*64))
    client.session.get = Mock(return_value=response({'new':True}))
    client.get_json('https://api.crossref.org/works/one')
    assert legacy.read_bytes() == before
    assert len(client.cache) == 1


def test_concurrent_duplicate_has_one_send(tmp_path):
    client = HarvestClient(tmp_path/'cache.jsonl',('1'*64))
    entered, release = threading.Event(), threading.Event()
    def send(*a,**k):
        entered.set()
        assert release.wait(3)
        return response({'ok':True})
    client.session.get = Mock(side_effect=send)
    with ThreadPoolExecutor(max_workers=2) as pool:
        one = pool.submit(client.get_json,'https://api.crossref.org/works/one')
        assert entered.wait(3)
        two = pool.submit(client.get_json,'https://api.crossref.org/works/one')
        release.set()
        assert one.result() == two.result() == {'ok':True}
    assert client.session.get.call_count == 1


def test_sync_failure_retains_response_and_blocks_next_send(tmp_path):
    path=tmp_path/'cache.jsonl'
    publish=Mock()
    client=HarvestClient(path,('1'*64),publish=publish)
    publish.side_effect=RuntimeError('conflicting writer')
    client.last_sync=-1000
    client.session.get=Mock(return_value=response({'ok':True}))
    with pytest.raises(HarvestCheckpointError,match='sync failed'):
        client.get_json('https://api.crossref.org/works/one')
    with pytest.raises(HarvestCheckpointError):
        client.get_json('https://api.crossref.org/works/two')
    assert client.session.get.call_count==1
    restored=HarvestClient(path,('1'*64))
    restored.session.get=Mock(side_effect=AssertionError('must reuse retained outcome'))
    assert restored.get_json('https://api.crossref.org/works/one')=={'ok':True}


@pytest.mark.parametrize('fault',['truncated','hash','unknown'])
def test_corrupt_checkpoint_fails_before_requests(tmp_path,fault):
    path=tmp_path/'cache.jsonl'
    client=HarvestClient(path,('1'*64))
    client.session.get=Mock(return_value=response({'ok':True}))
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
    client=HarvestClient(path,('1'*64))
    with pytest.raises(HarvestCheckpointError,match='another input'):
        HarvestClient(path,('2'*64))
    client.finish(complete=True)
    before=path.read_bytes()
    new=HarvestClient(path,('2'*64))
    assert path.with_name('harvest_response_cache_previous.jsonl').read_bytes()==before
    assert json.loads(path.read_text().splitlines()[0])['input_sha256']==('2'*64)
    assert not new.cache


def test_secret_headers_not_stored_and_changed_request_is_not_reused(tmp_path):
    path=tmp_path/'cache.jsonl'
    client=HarvestClient(path,('1'*64))
    client.session.get=Mock(return_value=response({'ok':True}))
    client.get_json('https://api.crossref.org/works/one',headers={'x-api-key':'example-secret'})
    client.get_json('https://api.crossref.org/works/one',headers={'x-api-key':'another-secret'})
    assert client.session.get.call_count==2
    assert 'secret' not in path.read_text()
    assert 'x-api-key' not in path.read_text()


def test_failed_response_is_not_success_cache(tmp_path):
    path=tmp_path/'cache.jsonl'
    client=HarvestClient(path,('1'*64))
    failed=Mock(status_code=404)
    failed.raise_for_status.side_effect=requests.HTTPError('not found')
    client.session.get=Mock(return_value=failed)
    assert client.get_json('https://api.crossref.org/works/missing') is None
    assert not client.cache
    assert not HarvestClient(path,('1'*64)).cache


def test_local_fsync_failure_stops_next_request(tmp_path,monkeypatch):
    client=HarvestClient(tmp_path/'cache.jsonl',('1'*64))
    client.session.get=Mock(return_value=response({'ok':True}))
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
    assert client.get_json('https://api.crossref.org/works/one') is None
    assert not HarvestClient(path,('1'*64)).cache

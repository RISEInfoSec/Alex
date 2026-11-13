from unittest.mock import Mock

import pytest
import requests
import pandas as pd

from alex.utils import http


@pytest.mark.parametrize('url',['https://api.openalex.org/works','https://api.openalex.org./works',
                                'https://openalex.org/works','https://other.openalex.org/works'])
def test_review_http_blocks_uncached_openalex_without_using_the_session(tmp_path,monkeypatch,url):
    monkeypatch.setattr(http,'CACHE',tmp_path/'cache.json')
    client=http.HttpClient();client.session.get=Mock(side_effect=AssertionError('provider request forbidden'))
    with pytest.raises(http.ProviderCoordinationRequired,match='shared private coordinator'):
        client.get_json(url)
    client.session.get.assert_not_called();assert not (tmp_path/'cache.json').exists()


def test_cross_source_redirect_cannot_bypass_provider_hold():
    class Adapter(requests.adapters.BaseAdapter):
        def __init__(self):self.sent=[]
        def send(self,request,**kwargs):
            self.sent.append(request.url);response=requests.Response();response.url=request.url;response.request=request
            response.status_code=302;response.headers['Location']='https://api.openalex.org/works';return response
        def close(self):pass
    session=http._ProviderGuardedSession();adapter=Adapter();session.mount('https://',adapter)
    with pytest.raises(requests.exceptions.RequestException,match='shared private coordinator'):
        session.get('https://source.example/works')
    assert adapter.sent==['https://source.example/works']


def test_discovery_does_not_turn_the_provider_hold_into_an_empty_result(tmp_path,monkeypatch):
    from alex.pipelines import discovery
    monkeypatch.setattr(http,'CACHE',tmp_path/'cache.json')
    monkeypatch.setattr(discovery.connector_config,'load',lambda:{'queries':['fixture'],'connectors':{}})
    monkeypatch.setattr(discovery.connector_config,'is_enabled',lambda config,name,default=True:name=='openalex')
    monkeypatch.setattr(discovery,'root_file',lambda *parts:tmp_path.joinpath(*parts))
    monkeypatch.setattr(discovery,'load_df',lambda _:pd.DataFrame())
    save=Mock();monkeypatch.setattr(discovery,'save_df',save)
    monkeypatch.setattr(discovery.openalex,'search',Mock(side_effect=http.ProviderCoordinationRequired('held')))
    with pytest.raises(http.ProviderCoordinationRequired):discovery.run()
    save.assert_not_called()


@pytest.mark.parametrize('stage',['harvest','citation_chain'])
def test_parallel_stages_do_not_turn_the_provider_hold_into_an_empty_result(tmp_path,monkeypatch,stage):
    from alex.pipelines import harvest,citation_chain
    module={'harvest':harvest,'citation_chain':citation_chain}[stage]
    monkeypatch.setattr(http,'CACHE',tmp_path/'cache.json')
    monkeypatch.setattr(module,'root_file',lambda *parts:tmp_path.joinpath(*parts))
    monkeypatch.setattr(module,'load_df',lambda _:pd.DataFrame([{'title':'Fixture','doi':'','authors':'',
        'venue':'','abstract':'','citation_count':1}]))
    monkeypatch.setattr(module.connector_config,'load',lambda:{'connectors':{}})
    name='_harvest_one' if stage=='harvest' else '_chain_one_candidate'
    monkeypatch.setattr(module,name,Mock(side_effect=http.ProviderCoordinationRequired('held')))
    save=Mock();monkeypatch.setattr(module,'save_df',save)
    with pytest.raises(http.ProviderCoordinationRequired):module.run()
    save.assert_not_called()


def test_apwg_does_not_convert_provider_hold_to_a_lookup_miss(monkeypatch):
    from alex.pipelines import apwg_import
    monkeypatch.setattr(apwg_import.openalex,'search',Mock(side_effect=http.ProviderCoordinationRequired('held')))
    with pytest.raises(http.ProviderCoordinationRequired):
        apwg_import.enrich_openalex(Mock(_host_blocked=Mock(return_value=False)),[{'title':'Fixture','apwg_year':2024}],1)

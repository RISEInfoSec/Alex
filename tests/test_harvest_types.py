import hashlib
import json
from unittest.mock import Mock

import pandas as pd
import pytest

from alex.discovery_types import paper_route_hold
from alex.pipelines import harvest, rescore, citation_chain
from alex.utils import io
from alex.utils.harvest_checkpoint import HarvestClient
from alex.utils.harvest_types import restore_crossref_types


def fixture(tmp_path, monkeypatch, kind='book-chapter', complete=True):
    monkeypatch.setattr('alex.utils.http.CACHE',tmp_path/'legacy.json')
    (tmp_path/'data').mkdir()
    row={'title':'OSINT methodology and cybersecurity','doi':'10.1234/type-test','authors':'A',
         'venue':'IEEE','year':2026,'abstract':'OSINT methodology cybersecurity',
         'citation_count':1000,'discovery_resource_type':''}
    frame=pd.DataFrame([row]);source=tmp_path/'data/accepted_candidates.csv'
    frame.to_csv(source,index=False)
    cache=tmp_path/'data/harvest_response_cache.jsonl'
    output=tmp_path/'data/accepted_harvested.csv'
    frame.to_csv(output,index=False)
    client=HarvestClient(cache,hashlib.sha256(source.read_bytes()).hexdigest(),publish=lambda:None,output_path=output)
    key=json.dumps({'url':'https://api.crossref.org/works/'+row['doi'],'params':{},'headers':{}},sort_keys=True)
    client._cache_put(key,{'message':{'DOI':row['doi'],'type':kind}})
    if complete:
        client.finish(complete=True, output_sha256=hashlib.sha256(output.read_bytes()).hexdigest())
        client.confirm_output()
    else:
        client.finish(complete=False)
    monkeypatch.setattr('requests.sessions.Session.request',Mock(side_effect=AssertionError('No new source requests')))
    return frame,cache


def test_retained_type_reaches_actual_rescore_before_acceptance(tmp_path,monkeypatch):
    frame,cache=fixture(tmp_path,monkeypatch)
    frame.to_csv(tmp_path/'data/accepted_harvested.csv',index=False)
    (tmp_path/'config').mkdir()
    (tmp_path/'config/venue_whitelist.json').write_text(json.dumps({'high_trust':['IEEE']}))
    (tmp_path/'config/query_registry.json').write_text(json.dumps({'queries':['OSINT','cybersecurity']}))
    (tmp_path/'config/quality_weights.json').write_text(json.dumps({
        'venue':.35,'citations':.40,'relevance':.25,'institution_bonus':10,
        'auto_include_threshold':0,'review_threshold':0,
        'preprint_auto_include_threshold':0,'preprint_review_threshold':0}))
    monkeypatch.setattr(io,'ROOT',tmp_path)
    rescore.run()
    assert pd.read_csv(tmp_path/'data/accepted_harvested.csv').empty
    metrics=pd.read_csv(tmp_path/'data/rescore_metrics.csv')
    assert metrics.iloc[0]['harvest_crossref_type']=='book-chapter'
    assert 'separate format review' in metrics.iloc[0]['document_type_hold']
    assert len(metrics.iloc[0]['harvest_crossref_type_evidence_sha256'])==64


@pytest.mark.parametrize('kind',['journal-article','proceedings-article','article','review','preprint'])
def test_paper_and_review_types_do_not_gain_nonpaper_hold(tmp_path,monkeypatch,kind):
    frame,_=fixture(tmp_path,monkeypatch,kind)
    restored=restore_crossref_types(frame,tmp_path)
    assert not paper_route_hold(restored.iloc[0])
    assert frame.iloc[0]['discovery_resource_type']==''


@pytest.mark.parametrize('kind',['monograph','edited-book','reference-book','journal','component'])
def test_book_and_container_records_require_format_review(tmp_path,monkeypatch,kind):
    frame,_=fixture(tmp_path,monkeypatch,kind)
    assert paper_route_hold(restore_crossref_types(frame,tmp_path).iloc[0])


@pytest.mark.parametrize('fault',['input','incomplete','digest','doi','contradiction'])
def test_mismatched_or_partial_evidence_fails_closed(tmp_path,monkeypatch,fault):
    frame,cache=fixture(tmp_path,monkeypatch,complete=fault!='incomplete')
    if fault=='input':
        (tmp_path/'data/accepted_candidates.csv').write_text('doi\n10.1234/another\n')
    elif fault=='digest':
        cache.write_text(cache.read_text().replace('book-chapter','book'))
    elif fault=='doi':
        from alex.utils.harvest_checkpoint import digest
        records=[json.loads(line) for line in cache.read_text().splitlines()]
        record=next(r for r in records if r.get('event')=='response')
        record['response']['message']['DOI']='10.1234/another'
        record['sha256']=digest({k:record[k] for k in ('request_sha256','response')})
        cache.write_text(''.join(json.dumps(r)+'\n' for r in records))
    elif fault=='contradiction':
        frame['harvest_crossref_type']='journal-article'
    with pytest.raises(ValueError):restore_crossref_types(frame,tmp_path)


def test_harvest_keeps_both_provider_types_and_does_not_release_prior_hold(monkeypatch):
    monkeypatch.setattr(harvest.crossref,'get_by_doi',lambda *a:{'DOI':'10.1234/type-test','type':'book'})
    monkeypatch.setattr(harvest.openalex,'search',lambda *a,**k:[{
        'title':'OSINT book','ids':{'doi':'https://doi.org/10.1234/type-test'},
        'type':'article','abstract_inverted_index':{'OSINT':[0]}}])
    result=harvest._harvest_one(None,{'title':'OSINT book','doi':'10.1234/type-test','abstract':''},'',False,'')
    assert result['harvest_crossref_type']=='book'
    assert result['harvest_openalex_type']=='article'
    assert paper_route_hold(result)


def test_forward_chain_requests_and_retains_source_type(monkeypatch):
    monkeypatch.setattr(citation_chain.openalex,'search',lambda *a,**k:[{'id':'https://openalex.org/W1'}])
    cited=Mock(return_value=[{'id':'https://openalex.org/W2','title':'OSINT chapter','type':'book-chapter'}])
    monkeypatch.setattr(citation_chain.openalex,'fetch_cited_by',cited)
    rows=citation_chain._chain_one_candidate(None,'seed','',1,1,False,'',1,1,{'osint'})
    assert 'type' in cited.call_args.kwargs['select'].split(',')
    assert rows[0]['discovery_resource_type']=='book-chapter'
    assert paper_route_hold(rows[0])


@pytest.mark.parametrize('fault',[None,'source_title','harvested_title','harvested_doi','missing_title'])
def test_returned_doi_type_requires_exact_request_and_harvested_title(tmp_path,monkeypatch,fault):
    frame,cache=fixture(tmp_path,monkeypatch)
    from alex.utils.harvest_checkpoint import digest
    records=[json.loads(line) for line in cache.read_text().splitlines()]
    record=next(r for r in records if r.get('event')=='response')
    original_doi=frame.iloc[0]['doi']
    returned_doi='10.1234/returned-chapter'
    message=record['response']['message']
    message['DOI']=returned_doi
    message['title']=[frame.iloc[0]['title']]
    frame['doi']=returned_doi
    if fault=='source_title':message['title']=['An unrelated work']
    if fault=='harvested_title':frame['title']='An unrelated work'
    if fault=='harvested_doi':frame['doi']=original_doi
    if fault=='missing_title':message.pop('title')
    record['sha256']=digest({k:record[k] for k in ('request_sha256','response')})
    cache.write_text(''.join(json.dumps(r)+'\n' for r in records))
    if fault:
        with pytest.raises(ValueError):restore_crossref_types(frame,tmp_path)
    else:
        restored=restore_crossref_types(frame,tmp_path).iloc[0]
        assert restored['doi']==returned_doi
        assert restored['title']==frame.iloc[0]['title']
        assert restored['harvest_crossref_requested_doi']==original_doi
        assert restored['harvest_crossref_type']=='book-chapter'
        assert paper_route_hold(restored)


def test_rescore_lineage_allows_verified_rollover_only(tmp_path,monkeypatch):
    from alex.utils.harvest_checkpoint import HarvestCheckpointError
    frame,cache=fixture(tmp_path,monkeypatch)
    (tmp_path/'config').mkdir()
    (tmp_path/'config/venue_whitelist.json').write_text(json.dumps({'high_trust':['IEEE']}))
    (tmp_path/'config/query_registry.json').write_text(json.dumps({'queries':['OSINT','cybersecurity']}))
    (tmp_path/'config/quality_weights.json').write_text(json.dumps({
        'venue':.35,'citations':.40,'relevance':.25,'institution_bonus':10,
        'auto_include_threshold':0,'review_threshold':0,'preprint_auto_include_threshold':0,
        'preprint_review_threshold':0}))
    monkeypatch.setattr(io,'ROOT',tmp_path)
    rescore.run()
    output=tmp_path/'data/accepted_harvested.csv'
    lineage=tmp_path/'data/.harvest_output_lineage.json'
    before=lineage.read_bytes()
    proof=json.loads(before)
    assert proof['rescore_output_sha256']==hashlib.sha256(output.read_bytes()).hexdigest()
    proof['harvest_output_sha256']='0'*64
    lineage.write_text(json.dumps(proof))
    with pytest.raises(HarvestCheckpointError,match='output unverified'):
        HarvestClient(cache,'2'*64,publish=lambda:None,output_path=output)
    lineage.write_bytes(before)
    resumed=HarvestClient(cache,'2'*64,publish=lambda:None,output_path=output)
    assert resumed.path.with_name('harvest_response_cache_previous.jsonl').is_file()

import pytest
from alex.pipelines import apwg_abstract_checkpoint as cache
from alex.pipelines import apwg_pdf_abstracts as pdf
from alex.pipelines.apwg_editorial_review import abstract_digest


@pytest.fixture
def saved(monkeypatch):
    e = {'doi':'10.1234/saved', 'title':'Saved original study', 'year':'2020',
         'abstract':'The complete original abstract from a verified source.',
         'abstract_source':'OpenAlex title/DOI verified'}
    e['abstract_sha256'] = abstract_digest(e['abstract'])
    monkeypatch.setattr(cache, 'checkpoint', lambda: {'entries':[e]})
    return {**e, 'abstract':'', 'abstract_source':''}, e


def test_restores_missing_text_but_preserves_available_source_text_and_identity(saved):
    row, e = saved
    result, restored = cache.restore(row)
    assert restored and result['abstract'] == e['abstract'] and not row['abstract']
    for k,v in [('doi','10.1234/other'),('title','Different'),('year','2021'),
                ('abstract','New provider version'),('in_existing_alex_corpus','true'),
                ('duplicate_review_status','hold_possible_variant')]:
        changed = {**row,k:v}
        assert cache.restore(changed) == (changed,False)
    e['abstract'] += ' modified'
    with pytest.raises(ValueError, match='digest'):
        cache.restore(row)


def test_enrichment_uses_checkpoint_without_network_request(tmp_path, monkeypatch, saved):
    import csv
    row, e = saved
    row['apwg_year']='2020'; row['apwg_paper_url']='https://docs.apwg.org/saved.pdf'
    src,out,audit=(tmp_path/p for p in ['source.csv','enriched.csv','audit.csv'])
    with src.open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(row));w.writeheader();w.writerow(row)
    monkeypatch.setattr(pdf,'fetch_pdf_abstract',lambda *a,**k:pytest.fail('Must reuse verified data'))
    summary=pdf.enrich(src,out,audit)
    assert summary['pdfs_attempted']==0
    assert summary['abstract_status_counts']['verified_abstract_checkpoint_restored']==1
    assert next(csv.DictReader(out.open()))['abstract_source']==e['abstract_source']


@pytest.mark.parametrize('saved_count,live_count', [('3','0'),('10','16'),('0','3')])
def test_citation_provider_priority_is_not_a_maximum_count_selection(monkeypatch, saved, saved_count, live_count):
    row, e = saved
    e.update(citation_count=saved_count, citation_count_source='OpenAlex cited_by_count')
    monkeypatch.setattr(cache, 'checkpoint', lambda: {'entries':[e],
        'snapshot_created_at':'2026-10-27T00:40:28Z', 'source_run':1,'source_artifact':2})
    row.update(citation_count=live_count,citation_count_source='Crossref is-referenced-by-count')
    restored, changed = cache.restore_citations(row)
    assert changed and restored['citation_count'] == saved_count
    assert restored['alternate_citation_count'] == live_count
    assert restored['citation_snapshot_created_at'] == '2026-10-27T00:40:28Z'
    assert cache.restore_citations(restored) == (restored,False)
    for k,v in [('doi','10.1234/other'),('year','2021'),('title','Changed'),
                ('in_existing_alex_corpus','true'),('duplicate_review_status','hold_possible_variant'),
                ('citation_count_source','OpenAlex cited_by_count')]:
        changed_row={**row,k:v}
        assert cache.restore_citations(changed_row)==(changed_row,False)

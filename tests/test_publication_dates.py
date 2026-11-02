from datetime import date,timedelta
from alex.publication_dates import crossref_publication_fields,recent_publications,apply_verified_dates,exact_date


def verified(value,**extra):
    return dict(title='A verified publication',publication_date=value,publication_date_source='https://publisher.example/paper',publication_date_status='verified',**extra)


def test_ninety_day_boundary_future_and_unknown_dates():
    now=date(2026,11,2)
    rows=[verified((now-timedelta(days=90)).isoformat()),verified((now-timedelta(days=91)).isoformat()),verified('2026-11-02'),verified('2026-11-03'),dict(title='Year only',year=2026,retrieved='2026-11-02'),verified('2026-10'),dict(title='Unverified',publication_date='2026-10-01')]
    assert [r['publication_date'] for r in recent_publications(rows,now)]==['2026-11-02','2026-08-04']


def test_discovery_listing_and_update_do_not_make_old_work_new():
    row=verified('2019-01-01',retrieved='2026-11-02',discovered_at='2026-11-02',updated_at='2026-11-02',year=2026)
    assert not recent_publications([row],date(2026,11,2))
    assert not crossref_publication_fields({'DOI':'10.1/a','created':{'date-parts':[[2026,11,2]]},'deposited':{'date-parts':[[2026,11,2]]},'indexed':{'date-parts':[[2026,11,2]]}})


def test_first_online_publication_precedes_new_print_issue():
    item={'DOI':'10.1/a','published-online':{'date-parts':[[2026,2,1]]},'published-print':{'date-parts':[[2026,10,1]]}}
    fields=crossref_publication_fields(item,date(2026,11,2))
    assert fields['publication_date']=='2026-02-01'
    assert not recent_publications([dict(title='Old online',**fields)],date(2026,11,2))


def test_month_year_and_invalid_calendar_dates_are_not_guessed():
    assert not crossref_publication_fields({'DOI':'10.1/a','published':{'date-parts':[[2026,10]]}})
    assert not crossref_publication_fields({'DOI':'10.1/a','published':{'date-parts':[[2026]]}})
    assert not crossref_publication_fields({'DOI':'10.1/a','published':{'date-parts':[[2026,2,30]]}})
    assert exact_date('2026-02-30') is None


def test_future_scheduled_publication_is_not_yet_published():
    assert not crossref_publication_fields({'DOI':'10.1/a','published':{'date-parts':[[2026,12,1]]}},date(2026,11,2))


def test_date_enrichment_is_additive_and_preserves_attribution(tmp_path):
    import json
    (tmp_path/'config').mkdir()
    (tmp_path/'config/publication_dates.json').write_text(json.dumps({'records':[dict(doi='10.1/a',**verified('2026-10-01'))]}))
    rows=[dict(doi='10.1/a',title='Original title',author='Original author',venue='Original journal',collection_source='Consensus')]
    result=apply_verified_dates(tmp_path,rows)
    assert result[0]['publication_date']=='2026-10-01'
    assert all(result[0][k]==v for k,v in rows[0].items())
    assert 'publication_date' not in rows[0]


def test_coarse_earlier_online_date_never_becomes_new_print_publication():
    item={'DOI':'10.1/a','published-online':{'date-parts':[[2020]]},'published-print':{'date-parts':[[2026,10,1]]}}
    assert not crossref_publication_fields(item,date(2026,11,2))


def test_arxiv_published_is_preserved_without_using_revision_date():
    import xml.etree.ElementTree as ET
    from alex.connectors.arxiv import _parse_entry
    entry=ET.fromstring('<entry xmlns="http://www.w3.org/2005/Atom"><id>http://arxiv.org/abs/2604.12345v2</id><title>Original paper</title><summary>Original abstract with sufficient text.</summary><published>2026-04-22T18:00:00Z</published><updated>2026-10-22T18:00:00Z</updated></entry>')
    result=_parse_entry(entry)
    assert result['publication_date']=='2026-04-22'
    assert result['publication_date_status']=='verified'

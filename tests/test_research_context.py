from datetime import date

import pytest
from bs4 import BeautifulSoup

from alex.collections import bibliography_item, build
from alex.research_context import earlier_research, historical_only, marker, NOTICE


@pytest.mark.parametrize('paper, expected', [
    ({'year': 2021}, True), ({'year': '2021.0'}, True),
    ({'year': 2022}, False), ({'year': ''}, False),
    ({'year': 'unknown'}, False), ({'year': 2020.5}, False),
    ({'publication_date': '2021-11-02', 'year': 2021}, False),
    ({'publication_date': '2021-11-01'}, True),
    ({'publication_date': '2021-02-30', 'year': 2021}, True),
])
def test_age_with_full_date_or_conservative_year(paper, expected):
    assert earlier_research(paper, date(2026, 11, 1)) is expected


def test_fifth_anniversary_leap_day():
    assert not earlier_research({'publication_date': '2020-02-29'}, date(2025, 2, 27))
    assert earlier_research({'publication_date': '2020-02-29'}, date(2025, 2, 28))


def test_historical_status_is_explicit_and_independent_of_age():
    assert not historical_only({'year': 1990})
    assert not historical_only({'historical_only': 'false'})
    assert historical_only({'historical_only': True})
    assert 'context-earlier' in marker({'year': 1990}, date(2026, 11, 1))
    assert 'context-historical' in marker({'year': 2026, 'historical_only': True}, date(2026, 11, 1))


def test_notice_only_inside_closed_paper_details_and_escaped():
    markup = bibliography_item({'title': '<script>x</script>', 'year': 2010, 'summary': '<b>evidence</b>'}, as_of=date(2026, 11, 1))
    soup = BeautifulSoup(markup, 'html.parser')
    assert soup.h3.get_text() == '<script>x</script>'
    assert soup.find('script') is None
    details = soup.select_one('details.paper-details')
    assert not details.has_attr('open')
    assert details.select_one('.research-context').get_text().endswith(NOTICE)
    assert soup.select_one('.context-marker').find_parent('details') is None
    assert not BeautifulSoup(bibliography_item({'year': 2026}, as_of=date(2026, 11, 1)), 'html.parser').select('.research-context')


def test_historical_bibliography_requires_opt_in(collection_site):
    source = [dict(title=f'Current {n}', year=2025, category='OSINT Methodology') for n in range(5)]
    source.append(dict(title='Historical example', year=2010, historical_only=True, category='OSINT Methodology'))
    output = build(collection_site, source)
    soup = BeautifulSoup(output['research/categories/osint-methodology/index.html'], 'html.parser')
    historical = soup.select_one('details.historical-view')
    assert historical and not historical.has_attr('open')
    assert historical.select_one('li.paper h3').get_text() == 'Historical example'
    assert len(soup.select('li.paper')) == len(source)


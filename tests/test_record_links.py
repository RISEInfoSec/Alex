import json
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from alex.record_links import public_record_url


def test_links_are_unique_and_ignore_display_id():
    papers = json.loads((Path(__file__).parents[1] / 'data/papers.json').read_text())
    urls = [public_record_url(paper) for paper in papers]
    assert len(set(urls)) == len(papers)
    for paper, url in zip(papers, urls):
        assert public_record_url({**paper, 'id': -999}) == url
        assert list(parse_qs(urlsplit(url).query)) == ['record']


def test_doi_and_bibliographic_fallback():
    assert public_record_url({'doi': 'https://doi.org/10.1234/TEST'}) == public_record_url({'doi': '10.1234/test'})
    assert public_record_url({'title': 'Same title', 'year': 2026}) != public_record_url({'title': 'Same title', 'year': 2025})

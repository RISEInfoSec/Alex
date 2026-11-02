import pytest
from alex.publication_status import build_index


def fixture():
    row = dict(review_candidate_id='weekly-paper', review_content_sha256='a'*64,
               title='Paper',authors='Author',abstract='Complete abstract',source_url='https://example.org/paper',
               year='2026.0',Category='OSINT',Investigation_Type='Other')
    public = dict(id=4,title='Paper',author='Author',summary='Complete abstract',source_url='https://example.org/paper',
                  year=2026,category='OSINT',investigation_type='Other')
    return row, public


def test_only_the_deployed_unchanged_target_establishes_publication():
    row, public = fixture()
    assert build_index([row],[public])['weekly-paper']['content_sha256']=='a'*64
    assert build_index([row],[]) == {}  # Removed or not yet deployed.
    for field in ('title','author','summary','source_url','year','category','investigation_type'):
        changed={**public,field:2025 if field=='year' else 'changed'}
        assert build_index([row],[changed]) == {}
    assert build_index([{**row,'review_candidate_id':''}],[public]) == {}


def test_ambiguous_publication_fails_instead_of_silently_reporting_success():
    row, public = fixture()
    with pytest.raises(ValueError):build_index([row],[public,public])
    with pytest.raises(ValueError):build_index([row,row],[public])

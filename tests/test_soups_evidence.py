import json
import pytest
from alex.pipelines.soups_evidence import crossref_matches, restore_evidence, openalex_citation_match, extract_cached_pdfs
from alex.pipelines.soups_checks import audit_selected
from alex.pipelines.soups_review import digest


def example():
    return dict(candidate_id='soups-example', title='A Paper: With a Subtitle', source_url='https://cups.cs.cmu.edu/soups/2010/proceedings/a.pdf', conference_year=2010, year=2010)


def test_crossref_requires_full_title_and_venue_and_holds_ambiguity():
    row = example()
    item = dict(DOI='10.1000/x', title=['A Paper'], subtitle=['With a Subtitle'],
                author=[dict(given='A',family='Author')], published={'date-parts':[[2010]]},
                **{'container-title':['Proceedings of the Symposium on Usable Privacy and Security']})
    assert crossref_matches([item], [row])[0]['doi'] == '10.1000/x'
    assert crossref_matches([{**item,'subtitle':['Other topic']}], [row]) == []
    assert crossref_matches([{**item,'container-title':['Unrelated conference']}], [row]) == []
    assert crossref_matches([item,{**item,'DOI':'10.1000/y'}], [row]) == []


def test_publication_year_conflict_is_preserved_as_a_hold():
    row = example()
    item = dict(DOI='10.1000/x', title=[row['title']], author=[dict(family='Author')],
                published={'date-parts':[[2009]]}, **{'container-title':['Symposium on Usable Privacy and Security']})
    result = crossref_matches([item], [row])[0]
    assert result['crossref_year'] == 2009
    assert result['conference_year'] == 2010
    assert result['publication_year_conflict']


def test_checkpoint_rejects_identity_drift_and_never_grants_publication(tmp_path):
    row = example()
    entry = {**row,'authors':'A. Author','doi':'10.1000/x','publication_approved':True}
    (tmp_path/'soups_bibliographic_evidence.json').write_text(json.dumps({'records':[entry]}))
    restored = restore_evidence(row,tmp_path)
    assert restored['authors'] == 'A. Author'
    assert restored['publication_approved'] is False
    with pytest.raises(ValueError,match='identity mismatch'):
        restore_evidence({**row,'source_url':'https://example.org/other'},tmp_path)


def test_audit_holds_missing_link_and_changed_approval():
    row = {**example(),'title':'Phishing research', 'abstract':'A research abstract about phishing attacks and fraud. '*5,
           'authors':'A. Author','publisher':'Publisher','venue':'Actual venue','review_number':1,
           'decision':'approved','decision_content_sha256':'stale',
           'duplicate_check':{'status':'no_match_found'}}
    report = audit_selected({'records':[row]},[])
    assert report['records'][0]['mechanical_status'] == 'hold'
    assert 'changed_reviewed_content' in report['records'][0]['mechanical_issues']
    assert 'pdf_link_not_verified' in report['records'][0]['mechanical_issues']
    assert report['publication_approved'] is False


def test_audit_accepts_successful_retry_and_does_not_bypass_quality():
    row = {**example(),'abstract':'A research abstract without attack-specific detail. '*5,
           'authors':'A. Author','publisher':'Publisher','venue':'Actual venue','review_number':1,
           'decision':'approved','duplicate_check':{'status':'no_match_found'}}
    row['decision_content_sha256'] = digest(row)
    report = audit_selected({'records':[row]},[dict(candidate_id=row['candidate_id'],error='transient',
                          retry={'status':200,'content_type':'application/pdf'})])
    result = report['records'][0]
    assert result['mechanical_status'] == 'pass_checked_metadata_and_pdf_link'
    assert result['quality_requires_review'] is True
    assert result['publication_approved'] is False


def test_citations_require_identity_and_hold_multiple_versions():
    row = {**example(),'authors':'A. Author; B. Writer'}
    item = dict(id='https://openalex.org/W1', title=row['title'], publication_year=2010,
                cited_by_count=0, doi='https://doi.org/10.1000/repository-version',
                authorships=[{'author':{'display_name':'A. Author'}}, {'author':{'display_name':'B. Writer'}}])
    result, status = openalex_citation_match([item], row)
    assert status == 'verified_version' and result['citation_count'] == 0
    assert 'doi' not in result
    assert result['citation_version_doi'].endswith('/repository-version')
    assert openalex_citation_match([item,{**item,'id':'https://openalex.org/W2'}],row)[1] == 'ambiguous_author_matched_versions'
    assert openalex_citation_match([{**item,'publication_year':2009}],row)[0] is None
    assert openalex_citation_match([{**item,'authorships':[]}],row)[0] is None


def test_pdf_extractor_never_deletes_files_outside_its_staging_directory(tmp_path):
    config = tmp_path/'config'; config.mkdir()
    manifest = config/'soups_review_manifest.json'
    manifest.write_text(json.dumps({'records':[example()]}))
    unrelated = tmp_path/'unrelated.pdf'; unrelated.write_bytes(b'%PDF-test')
    log = tmp_path/'fetch-log.json'
    log.write_text(json.dumps([dict(candidate_id='soups-example', file=str(unrelated), sha256='untrusted')]))
    with pytest.raises(ValueError, match='outside task staging'):
        extract_cached_pdfs(log, manifest, tmp_path/'result.json')
    assert unrelated.exists()

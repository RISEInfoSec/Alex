from alex.pipelines.soups_review import (
    digest, duplicate_check, enrich_presentation, identity, legacy_records,
    merge_state, usenix_records,
    attribution_fields, LABEL,
)
import pytest


def test_lightning_talk_with_authors_is_not_research_paper():
    html = '''<article class="node-session"><h2>Lightning Talks</h2>
    <article class="node-paper"><h2><a href="/presentation/a">Security for Cities</a></h2>
    <div class="field-name-field-paper-people-text">Someone, <em>University</em></div>
    </article></article>'''
    row = usenix_records(html, 2020, 'https://www.usenix.org/conference/soups2020/')[0]
    assert row['document_type'] != 'research_paper'
    assert row['publication_approved'] is False


def test_legacy_front_matter_and_extensionless_papers():
    html = '''<h2>PROGRAM</h2><p><a href="proceedings/front-matter.pdf">Proceedings front matter</a></p>
    <p><a href="proceedings/a6_Rader">Stories as Informal Lessons about Security</a></p>
    <h2>POSTERS</h2><a href="posters/security.pdf">A substantial poster title</a>'''
    rows = legacy_records(html, 2012, 'https://cups.cs.cmu.edu/soups/2012/program.html')
    assert [r['document_type'] for r in rows] == ['proceedings_front_matter', 'research_paper', 'poster_or_poster_showcase']
    assert rows[1]['source_url'].endswith('/proceedings/a6_Rader')


def test_content_changes_revoke_decision_but_keep_number_and_disappearing_records():
    row = dict(candidate_id='a', title='Old title', authors='A', year=2025, source_url='https://example.org/a', abstract='original')
    prior = {**row, 'content_sha256':digest(row), 'review_number':7, 'decision':'approved'}
    merged = merge_state([{**row, 'abstract':'changed'}], {'records':[prior, {'candidate_id':'missing','decision':'rejected'}]})
    assert merged[0]['decision'] == 'pending_content_changed'
    assert merged[0]['review_number'] == 7
    assert merged[1]['decision'] == 'rejected'
    assert merged[1]['source_missing_on_refresh']
    assert all(r['publication_approved'] is False for r in merged)


def test_exact_doi_title_url_and_possible_variant_are_held():
    corpus = [dict(title='A Study of Financial Scams in Online Communities', doi='10.1000/x', source_url='https://example.org/a')]
    for row in [dict(title='Different title',doi='https://doi.org/10.1000/X',source_url='https://example.org/b'),
                dict(title='A Study of Financial Scams in Online Communities',source_url='https://example.org/b'),
                dict(title='Different title',source_url='https://example.org/a#part')]:
        assert duplicate_check(row, corpus)['status'] == 'existing_match'
    row = dict(title='A Study of Financial Scam in Online Communities',source_url='https://example.org/b')
    assert duplicate_check(row, corpus)['status'] == 'possible_variant_hold'


def test_individual_citation_must_match_title_and_year():
    row = dict(title='A Research Paper', year=2025, source_url='https://www.usenix.org/paper')
    html = '''<meta name="citation_title" content="A Research Paper">
    <meta name="citation_author" content="A. Author"><meta name="citation_publication_date" content="2025">
    <meta name="citation_conference_title" content="SOUPS 2025">publisher = {USENIX Association}'''
    result = enrich_presentation(row, html, row['source_url'])
    assert result['authors'] == 'A. Author'
    assert result['doi'] == ''
    with pytest.raises(ValueError, match='year conflict'):
        enrich_presentation({**row, 'year':2024}, html, row['source_url'])
    with pytest.raises(ValueError, match='title mismatch'):
        enrich_presentation({**row, 'title':'Unrelated'}, html, row['source_url'])


def test_source_fragment_does_not_renumber_identity():
    assert identity('https://www.usenix.org/paper#abstract') == identity('https://www.usenix.org/paper/')


def test_user_collection_attribution_and_links():
    fields = attribution_fields()
    assert fields['collection_source'] == 'SOUPS (Symposium On Usable Privacy and Security) and USENIX (the Advanced Computing Systems Association)'
    assert fields['collection_links'] == [dict(name='SOUPS', url='https://soups.page/'),
                                         dict(name='USENIX', url='https://www.usenix.org/')]
    fields['collection_links'][0]['url'] = 'changed'
    assert attribution_fields()['collection_links'][0]['url'] == 'https://soups.page/'


def test_selection_decision_evidence_survives_refresh():
    row = dict(candidate_id='a', title='A paper', authors='A', year=2025, source_url='https://example.org/a', abstract='original')
    prior = {**row, 'content_sha256':digest(row), 'decision':'approved', 'review_number':15,
             'decision_basis':'User approval', 'decision_date':'2026-10-27', 'decision_content_sha256':digest(row)}
    result = merge_state([dict(row)], {'records':[prior]})[0]
    assert result['decision'] == 'approved'
    assert result['decision_basis'] == 'User approval'
    assert result['decision_content_sha256'] == digest(row)
    assert result['publication_approved'] is False

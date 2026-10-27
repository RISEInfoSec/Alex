import csv

import pytest

from alex.pipelines import apwg_editorial_review as editorial
from alex.pipelines import apwg_classification_review as review
from alex.pipelines import apwg_pdf_abstracts as pdf


@pytest.fixture
def approved(monkeypatch):
    raw = 'We investigate security \ue001aws and exposed plaintext \ue000les in phishing kits. ' * 4
    corrected = raw.replace('\ue000', 'fi').replace('\ue001', 'fl').strip()
    entry = {
        'title': 'Reviewed Ransomware Economics', 'doi': '10.1234/reviewed', 'year': 2023,
        'category': 'Cybercrime & Fraud', 'investigation_type': 'Other',
        'selection_approved': True, 'classification_approved': True,
        'reviewed_abstract_sha256': editorial.abstract_digest(raw),
        'approved_abstract_sha256': editorial.abstract_digest(corrected),
        'abstract_glyph_replacements': {'\ue000': 'fi', '\ue001': 'fl'},
    }
    monkeypatch.setattr(editorial, 'decisions', lambda: {entry['doi']: entry})
    row = {'title': entry['title'], 'doi': entry['doi'], 'year': '2023',
           'apwg_year': '2023', 'abstract': raw.strip(), 'abstract_source': 'Original PDF abstract',
           'authors': 'Author', 'venue': '2023 eCrime', 'in_existing_alex_corpus': 'false'}
    return row, corrected


def test_approved_other_is_preserved_without_phishing_fallback_or_model_call(approved):
    row, corrected = approved
    def no_model(_):
        raise AssertionError('User-reviewed decisions must not be overwritten by a model')
    result = review.review_row(row, classifier=no_model)
    assert result['editorial_selection_status'] == 'approved'
    assert result['editorial_classification_status'] == 'approved'
    assert result['classification_status'] == 'editorial_classification_approved'
    assert result['proposed_investigation_type'] == 'Other'
    assert result['abstract'] == corrected
    assert result['publication_approved'] == 'false'
    assert 'publication authorization pending' in result['review_flags']


@pytest.mark.parametrize('field,value', [
    ('doi', '10.1234/different'), ('title', 'Different Research'), ('year', '2022'),
    ('abstract', 'A changed abstract or new extraction must be reviewed again.'),
])
def test_approval_does_not_transfer_to_changed_identity_or_content(approved, field, value):
    row, _ = approved
    changed = {**row, field: value}
    result = review.review_row(changed, classifier=lambda _: {
        'Category': 'Cybercrime & Fraud', 'Investigation_Type': 'Phishing Analysis',
        'OSINT_Source_Types': []})
    assert result['editorial_selection_status'] == 'not_reviewed'
    assert result['classification_status'] != 'editorial_classification_approved'
    assert result['publication_approved'] == 'false'


def test_glyph_cleanup_is_idempotent_and_never_applied_globally(approved):
    row, corrected = approved
    assert editorial.normalized_abstract(row) == (corrected, True)
    assert editorial.normalized_abstract({**row, 'abstract': corrected}) == (corrected, False)
    other = {**row, 'doi': '10.1234/unreviewed'}
    assert editorial.normalized_abstract(other) == (row['abstract'], False)


def test_existing_record_wins_over_editorial_manifest(approved):
    row, _ = approved
    result = review.review_row({**row, 'in_existing_alex_corpus': 'true'})
    assert result['classification_status'] == 'existing_alex_record_preserved'
    assert result['editorial_selection_status'] == 'not_reviewed'


def test_pdf_review_output_gets_verified_cleanup_without_modifying_source(tmp_path, monkeypatch, approved):
    row, corrected = approved
    row['apwg_paper_url'] = 'https://docs.apwg.org/reviewed.pdf'
    raw = row['abstract']; row['abstract'] = ''; row['abstract_source'] = ''
    source, output, audit = (tmp_path / p for p in ['source.csv', 'output.csv', 'audit.csv'])
    with source.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=list(row)); w.writeheader(); w.writerow(row)
    original = source.read_bytes()
    monkeypatch.setattr(pdf, 'fetch_pdf_abstract', lambda *a, **k: (raw, 'extracted_verified_abstract'))
    monkeypatch.setattr(pdf.time, 'sleep', lambda _: None)
    pdf.enrich(source, output, audit)
    result = next(csv.DictReader(output.open()))
    assert result['abstract'] == corrected
    assert 'visually verified' in result['abstract_source']
    assert source.read_bytes() == original
    assert not list(tmp_path.glob('*.pdf'))


def test_real_manifest_records_the_approved_decisions_without_release_authorization():
    from alex.utils.io import load_json, root_file
    from alex.pipelines.classify import CATEGORIES, INVESTIGATION_TYPES
    manifest = load_json(root_file('config', 'apwg_editorial_decisions.json'))
    assert manifest['publication_approved'] is False
    rows = manifest['papers']
    assert len(rows) == len({r['doi'] for r in rows}) == 38
    assert all(r['selection_approved'] and r['classification_approved'] for r in rows)
    assert all(r['category'] in CATEGORIES and r['investigation_type'] in INVESTIGATION_TYPES for r in rows)
    numbered = {r['review_number']: r for r in rows}
    assert numbered[9]['investigation_type'] == numbered[10]['investigation_type'] == 'Other'
    assert numbered[12]['category'] == 'AI/ML for Security'
    assert numbered[14]['investigation_type'] == 'Other'
    assert numbered[16]['category'] == 'OSINT Methodology'
    assert numbered[22]['investigation_type'] == 'Attribution'
    assert numbered[24]['category'] == 'Digital Forensics & Evidence'
    assert numbered[28]['category'] == 'AI/ML for Security'
    assert (numbered[31]['category'], numbered[31]['investigation_type']) == ('OSINT Methodology', 'Other')
    assert numbered[34]['category'] == 'Dark Web & Underground'
    assert (numbered[36]['category'], numbered[36]['investigation_type']) == ('Social Media & SOCMINT', 'Social Media Analysis')
    assert (numbered[37]['category'], numbered[37]['investigation_type']) == ('Cybercrime & Fraud', 'Other')
    assert manifest['held_papers'] == []
    assert numbered[21]['approved_abstract_sha256'] == numbered[21]['abstract_override']['sha256']
    assert set(numbered) == set(range(1,39))
    assert numbered[8]['abstract_glyph_replacements']['\ue000'] == 'fi'
    assert numbered[8]['abstract_glyph_replacements']['security\ue001aws'] == 'security flaws'



def test_user_preferred_openalex_version_is_accepted_verbatim(approved, monkeypatch):
    row, _ = approved
    entries = editorial.decisions()
    entry = entries[row['doi']]
    alternate = 'The verified indexer version may contain different original wording.'
    entry['preferred_abstract_source'] = 'OpenAlex title/DOI verified'
    entry['preferred_abstract_sha256'] = editorial.abstract_digest(alternate)
    changed = {**row, 'abstract': alternate, 'abstract_source': entry['preferred_abstract_source']}
    assert editorial.decision_for(changed)[1] == 'approved'
    assert editorial.normalized_abstract(changed) == (alternate, False)
    result = review.review_row(changed, classifier=lambda _: (_ for _ in ()).throw(AssertionError('no model')))
    assert result['editorial_selection_status'] == 'approved'
    assert result['abstract'] == alternate
    assert result['publication_approved'] == 'false'


def test_preferred_hash_requires_recorded_source_and_new_changes_still_hold(approved):
    row, _ = approved
    entry = editorial.decisions()[row['doi']]
    entry['preferred_abstract_source'] = 'OpenAlex title/DOI verified'
    entry['preferred_abstract_sha256'] = editorial.abstract_digest('Approved indexer version')
    assert editorial.decision_for({**row, 'abstract': 'Approved indexer version',
                                  'abstract_source': 'Unknown source'})[0] is None
    assert editorial.decision_for({**row, 'abstract': 'An unreviewed future indexer version',
                                  'abstract_source': 'OpenAlex title/DOI verified'})[0] is None


@pytest.mark.parametrize('changed_abstract', [False, True])
def test_explicit_hold_survives_score_and_new_abstract_until_reviewed(monkeypatch, changed_abstract):
    from copy import deepcopy
    entry = deepcopy(editorial.decisions()['10.1109/ecrime.2009.5342609'])
    entry['editorial_hold'] = True
    entry['reason'] = 'Abstract completeness verification pending'
    monkeypatch.setattr(editorial, 'decisions', lambda: {entry['doi']: entry})
    row = {'title': entry['title'], 'doi': entry['doi'], 'year': str(entry['year']),
           'abstract': 'Updated original abstract' if changed_abstract else 'Short background only',
           'venue': '2009 eCrime', 'in_existing_alex_corpus': 'false'}
    def no_model(_):
        raise AssertionError('An explicit editorial hold must not call the classifier')
    result = review.review_row(row, classifier=no_model)
    assert result['editorial_selection_status'] == 'held'
    assert result['classification_status'] == 'editorial_hold'
    assert result['proposed_category'] == ''
    assert result['publication_approved'] == 'false'
    assert 'completeness' in result['review_flags']
    existing = review.review_row({**row, 'in_existing_alex_corpus': 'true'}, classifier=no_model)
    assert existing['classification_status'] == 'existing_alex_record_preserved'


def test_author_exception_is_identity_source_and_content_bound_and_idempotent(tmp_path, monkeypatch):
    entry = editorial.decisions()['10.1109/ecrime.2009.5342609']
    correction = entry['abstract_override']
    # The real source version is exercised by the artifact replay. Here a
    # controlled hash verifies the same guards without duplicating its text.
    from copy import deepcopy
    entry = deepcopy(entry)
    entry['editorial_hold'] = True
    entry['abstract_override']['replaces_sha256'] = editorial.abstract_digest('Reviewed short abstract')
    row = {'doi': entry['doi'], 'title': entry['title'], 'year': str(entry['year']),
           'abstract': 'Reviewed short abstract', 'abstract_source': correction['replaces_source']}
    from unittest.mock import patch
    with patch.object(editorial, 'decisions', return_value={entry['doi']: entry}):
        fixed, changed = editorial.apply_abstract_override(row)
        assert changed and fixed['abstract'] == ' '.join(correction['abstract'].split())
        assert row['abstract'] == 'Reviewed short abstract'
        assert editorial.apply_abstract_override(fixed) == (fixed, False)
        for field, value in [('doi','10.1234/other'), ('title','Different'), ('year','2010'),
                             ('abstract','New OpenAlex version'), ('abstract_source','Other'),
                             ('in_existing_alex_corpus','true'),
                             ('duplicate_review_status','hold_possible_variant')]:
            changed_row = {**row, field:value}
            assert editorial.apply_abstract_override(changed_row) == (changed_row, False)
        source, output, audit = (tmp_path / p for p in ['input.csv', 'output.csv', 'audit.csv'])
        row['apwg_paper_url'] = 'https://ieeexplore.ieee.org/document/5342609/'
        with source.open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=list(row))
            writer.writeheader(); writer.writerow(row)
        monkeypatch.setattr(pdf, 'fetch_pdf_abstract', lambda *a, **k: pytest.fail('No PDF request'))
        summary = pdf.enrich(source, output, audit)
        enriched = next(csv.DictReader(output.open()))
        assert enriched['abstract'] == fixed['abstract']
        assert enriched['abstract_source'] == fixed['abstract_source']
        assert summary['abstract_status_counts']['verified_author_abstract_replacement'] == 1
        result = review.review_row(enriched, classifier=lambda _: pytest.fail('No classifier'))
        assert result['editorial_selection_status'] == 'held'
        assert result['editorial_classification_status'] == 'approved'
        assert result['proposed_category'] == 'Cybercrime & Fraud'
        assert result['publication_approved'] == 'false'
        unreviewed = review.review_row({**enriched, 'abstract': 'Changed upstream abstract'})
        assert unreviewed['editorial_classification_status'] == 'held'
        assert unreviewed['proposed_category'] == ''
        entry['abstract_override']['abstract'] += ' tampered'
        with pytest.raises(ValueError, match='digest'):
            editorial.apply_abstract_override(row)

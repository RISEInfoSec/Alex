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


def test_real_manifest_records_the_13_approved_decisions_without_release_authorization():
    from alex.utils.io import load_json, root_file
    from alex.pipelines.classify import CATEGORIES, INVESTIGATION_TYPES
    manifest = load_json(root_file('config', 'apwg_editorial_decisions.json'))
    assert manifest['publication_approved'] is False
    rows = manifest['papers']
    assert len(rows) == len({r['doi'] for r in rows}) == 13
    assert all(r['selection_approved'] and r['classification_approved'] for r in rows)
    assert all(r['category'] in CATEGORIES and r['investigation_type'] in INVESTIGATION_TYPES for r in rows)
    numbered = {r['review_number']: r for r in rows}
    assert numbered[9]['investigation_type'] == numbered[10]['investigation_type'] == 'Other'
    assert numbered[12]['category'] == 'AI/ML for Security'
    assert numbered[8]['abstract_glyph_replacements'] == {'\ue000': 'fi', '\ue001': 'fl'}

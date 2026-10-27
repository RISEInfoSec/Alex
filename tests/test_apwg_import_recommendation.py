import csv
import pytest
from alex.pipelines import apwg_editorial_review as editorial
from alex.pipelines import apwg_import_recommendation as rec


@pytest.fixture
def approved(monkeypatch):
    abstract = 'An original phishing study with verified metadata.'
    entry = {'doi': '10.1234/paper', 'title': 'Phishing Study', 'year': 2020,
             'category': 'Cybercrime & Fraud', 'investigation_type': 'Phishing Analysis',
             'selection_approved': True, 'classification_approved': True,
             'reviewed_abstract_sha256': editorial.abstract_digest(abstract),
             'approved_abstract_sha256': editorial.abstract_digest(abstract)}
    entries = {entry['doi']: entry}
    monkeypatch.setattr(editorial, 'decisions', lambda: entries)
    monkeypatch.setattr(rec, 'decisions', lambda: entries)
    return {'doi': entry['doi'], 'title': entry['title'], 'year': '2020',
            'abstract': abstract, 'authors': 'A. Researcher', 'venue': 'eCrime',
            'quality_review_status': 'human_quality_review',
            'editorial_selection_status': 'approved', 'editorial_classification_status': 'approved',
            'proposed_category': entry['category'], 'proposed_investigation_type': entry['investigation_type']}


def test_existing_is_suppressed_even_if_marked_approved_and_source_is_unchanged(tmp_path, approved):
    existing = {**approved, 'doi': '10.1234/existing', 'in_existing_alex_corpus': 'true'}
    rows = [approved, existing]
    fields = sorted({k for r in rows for k in r})
    for name in ['review.csv', 'bibliography.csv']:
        with (tmp_path / name).open('w', newline='') as f:
            w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)
    before = (tmp_path / 'review.csv').read_bytes()
    summary = rec.build(tmp_path/'review.csv', tmp_path/'bibliography.csv', tmp_path/'out')
    assert summary['records_audited'] == 2
    assert summary['candidate_additions'] == summary['approved_pending_release'] == 1
    assert summary['suppressed_existing'] == 1 and summary['publication_approvals'] == 0
    additions = list(csv.DictReader((tmp_path/'out/apwg_additions_review.csv').open()))
    assert [r['doi'] for r in additions] == [approved['doi']]
    assert (tmp_path/'review.csv').read_bytes() == before


@pytest.mark.parametrize('changes,disposition', [
    ({'abstract': 'A changed unreviewed abstract'}, 'hold_approval_drift'),
    ({'requires_bibliographic_review': 'true'}, 'hold_metadata'),
    ({'publication_year_conflict': 'Unresolved conflict'}, 'hold_metadata'),
    ({'quality_review_status': 'hold_core_term_gate'}, 'hold_core_term_gate'),
    ({'quality_review_status': 'hold_relevance_floor'}, 'hold_relevance_floor'),
    ({'duplicate_review_status': 'hold_possible_variant'}, 'hold_duplicate_review'),
    ({'proposed_category': 'Malware & Exploits'}, 'hold_human_review'),
])
def test_approval_never_overrides_drift_metadata_duplicates_or_quality(approved, changes, disposition):
    assert rec.recommendation({**approved, **changes})[0] == disposition


def test_mismatched_artifacts_fail_instead_of_silently_dropping_a_paper(tmp_path, approved):
    for filename, rows in [('review.csv', [approved]), ('bib.csv', [{**approved, 'year':'2019'}])]:
        with (tmp_path/filename).open('w', newline='') as f:
            w=csv.DictWriter(f, fieldnames=list(approved));w.writeheader();w.writerows(rows)
    with pytest.raises(ValueError, match='identities'):
        rec.build(tmp_path/'review.csv', tmp_path/'bib.csv', tmp_path/'out')

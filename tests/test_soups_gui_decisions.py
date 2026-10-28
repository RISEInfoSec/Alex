from copy import deepcopy
import pytest
from alex.pipelines.soups_gui_decisions import apply_submissions
from alex.pipelines.soups_review import digest


def fixture():
    papers = [dict(candidate_id=f'p{i}', review_number=i, title=f'Paper {i}', year=2026, authors='A', source_url=f'https://example.org/{i}', abstract='a', document_type='poster_extended_abstract', decision='pending', publication_approved=False) for i in (119, 120)]
    rows = [dict(candidate_id=p['candidate_id'], review_number=p['review_number'], batch=7, revision=1, submission_id='receipt1', user_id='owner', content_sha256=digest(p), decision='rejected' if p['review_number']==120 else 'approved', created_at='2026-10-27T18:00:00Z') for p in papers]
    return {'records':papers}, rows


def test_explicit_gui_submission_applies_and_replays_without_publication():
    manifest, rows = fixture()
    result, audit = apply_submissions(manifest, rows)
    assert (result['approved_candidates'],result['rejected_candidates']) == (1,1)
    assert all(not r['publication_approved'] for r in result['records'])
    replay, _ = apply_submissions(result, rows)
    assert result == replay
    assert manifest['records'][0]['decision'] == 'pending'


def test_stale_partial_and_draft_records_do_not_apply():
    manifest, rows = fixture()
    for bad in [rows[:1], [dict(rows[0],content_sha256='wrong'),rows[1]], [dict(rows[0],decision='pending'),rows[1]]]:
        with pytest.raises(ValueError):
            apply_submissions(manifest, bad)
    assert all(r['decision']=='pending' for r in manifest['records'])


def test_newest_revision_wins_and_old_receipt_cannot_undo_it():
    manifest, rows = fixture()
    newer = [dict(r,revision=2,submission_id='receipt2',decision='approved') for r in rows]
    result,_ = apply_submissions(manifest, rows+newer)
    assert result['approved_candidates'] == 2
    replay,_ = apply_submissions(result,rows)
    assert replay == result


def test_other_collections_are_not_applied_to_soups():
    manifest, rows = fixture()
    result, audit = apply_submissions(manifest,[dict(r,collection='apwg') for r in rows])
    assert audit == []
    assert all(r['decision']=='pending' for r in result['records'])


def test_sealed_batch_override_preserves_original_paper_numbers():
    manifest, rows = fixture()
    for paper in manifest['records']:
        paper['review_batch'] = 15
    rows = [dict(r, batch=15) for r in rows]
    result, audit = apply_submissions(manifest, rows)
    assert [p['review_number'] for p in result['records']] == [119, 120]
    assert audit[0]['batch'] == 15
    with pytest.raises(ValueError):
        apply_submissions(manifest, rows[:1])

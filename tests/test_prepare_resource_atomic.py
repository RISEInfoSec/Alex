from copy import deepcopy

import pytest

from tools.content_review import prepare_resource


def test_failed_assessment_does_not_mutate_the_manifest_row(monkeypatch):
    stage = {'actual_type': 'best_practice_guide', 'content_sha256': 'a' * 64,
             'author': 'Example', 'publication_date': '2026-01',
             'publication_version': '1', 'source_receipt': 'fixture',
             'source_sha256': 'b' * 64, 'text_sha256': 'c' * 64,
             'text_complete': True}
    row = {'content_sha256': 'a' * 64, 'decision': 'pending',
           'preflight': {'checks': {gate: {'status': 'passed', 'content_sha256': 'a' * 64,
                                            'evidence': {'fixture': True}}
                                    for gate in ('format', 'access', 'duplicates')}}}
    before = deepcopy(row)
    monkeypatch.setattr(prepare_resource, 'validate_staging', lambda _: stage)
    def reject(_):
        raise ValueError('assessment rejected')
    monkeypatch.setattr(prepare_resource, 'validate_assessment', reject)
    with pytest.raises(ValueError, match='assessment rejected'):
        prepare_resource.prepare(row, {}, {}, 'reason', 'x' * 200, '2026-01-01T00:00:00Z')
    assert row == before


def test_success_updates_the_existing_row_only_after_validation(monkeypatch):
    stage = {'actual_type': 'best_practice_guide', 'content_sha256': 'a' * 64,
             'author': 'Example', 'publication_date': '2026-01',
             'publication_version': '1', 'source_receipt': 'fixture',
             'source_sha256': 'b' * 64, 'text_sha256': 'c' * 64,
             'text_complete': True}
    row = {'content_sha256': 'a' * 64, 'decision': 'pending',
           'preflight': {'checks': {gate: {'status': 'passed', 'content_sha256': 'a' * 64,
                                            'evidence': {'fixture': True}}
                                    for gate in ('format', 'access', 'duplicates')}}}
    monkeypatch.setattr(prepare_resource, 'validate_staging', lambda _: stage)
    monkeypatch.setattr(prepare_resource, 'validate_assessment', lambda _: None)
    monkeypatch.setattr(prepare_resource, 'validate_taxonomy', lambda _: None)
    monkeypatch.setattr(prepare_resource, 'dry_run', lambda _: {'fixture': True})
    monkeypatch.setattr(prepare_resource, 'corpus_value', lambda _: {'fixture': True})
    result = prepare_resource.prepare(row, {'criteria': {}, 'limitations': 'fixture'}, {},
                                      'reason', 'x' * 200, '2026-01-01T00:00:00Z')
    assert result is row
    assert row['manual_vote_required'] is True
    assert row['review_ready'] is False
    assert row['preflight']['checks']['duplicates']['evidence'] == {'fixture': True}

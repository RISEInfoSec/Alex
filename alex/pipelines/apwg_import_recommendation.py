"""Audit editorial approvals and export a review-only additions queue.

Existing ALEX records remain in the full audit but are suppressed from every
candidate queue. No output grants publication permission or writes the corpus.
"""
from __future__ import annotations
import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from alex.pipelines.apwg_editorial_review import decision_for, decisions
from alex.utils.text import clean, normalize_title


def identity(row: dict) -> tuple[str, str, str]:
    return (clean(row.get('doi')).lower().removeprefix('https://doi.org/'),
            normalize_title(row.get('title', '')), clean(row.get('year')))


def recommendation(row: dict) -> tuple[str, str]:
    if (clean(row.get('in_existing_alex_corpus')).lower() == 'true' or
            row.get('duplicate_review_status') == 'exact_doi_or_title_match' or
            row.get('classification_status') == 'existing_alex_record_preserved'):
        return 'suppressed_existing_alex', 'Preserve existing ALEX record; do not add again'
    if row.get('duplicate_review_status') == 'hold_possible_variant':
        return 'hold_duplicate_review', 'Resolve publication identity before selection'
    entry, status = decision_for(row)
    if status == 'rejected':
        return 'excluded_editorial_rejection', entry['reason']
    if status == 'held':
        return 'hold_editorial', entry['reason']
    if entry is None and status.startswith('reviewed_'):
        return 'hold_approval_drift', 'Identity or abstract changed; explicit re-review required'
    q = clean(row.get('quality_review_status'))
    if q.startswith('hold_'):
        actions = {
            'hold_missing_abstract': 'Recover a complete original abstract from a legitimate source',
            'hold_core_term_gate': 'Verify abstract and venue; inspect core-term evidence without keyword stuffing',
            'hold_relevance_floor': 'Inspect query-term coverage and actual investigative relevance; no automatic exception',
            'hold_below_review_threshold': 'Verify citations, original year, venue and abstract; retain score hold',
        }
        return q, actions.get(q, 'Individual quality review required')
    metadata = (not all(clean(row.get(k)) for k in ('doi', 'authors', 'year', 'venue', 'abstract')) or
                clean(row.get('requires_bibliographic_review')).lower() == 'true' or
                bool(clean(row.get('publication_year_conflict'))))
    if metadata:
        return 'hold_metadata', 'Resolve absent or conflicting bibliographic evidence'
    if (status == 'approved' and row.get('editorial_selection_status') == 'approved' and
            row.get('editorial_classification_status') == 'approved' and
            row.get('proposed_category') == entry['category'] and
            row.get('proposed_investigation_type') == entry['investigation_type'] and
            q in {'provisional_auto_threshold', 'human_quality_review'}):
        return 'editorially_approved_pending_release', 'Eligible for controlled import recommendation; publication not authorized'
    return 'hold_human_review', 'Editorial selection/classification not verified against manifest'


def write_csv(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(rows)


def build(review_path: Path, bibliography_path: Path, output_dir: Path) -> dict:
    with review_path.open(encoding='utf-8', newline='') as f:
        review = list(csv.DictReader(f))
    with bibliography_path.open(encoding='utf-8', newline='') as f:
        bibliography = list(csv.DictReader(f))
    if not review or not bibliography:
        raise ValueError('Empty review/bibliography: no recommendation generated')
    by_identity = {identity(r): r for r in bibliography}
    if len(by_identity) != len(bibliography):
        raise ValueError('Duplicate bibliography identities require review')
    if len({identity(r) for r in review}) != len(review):
        raise ValueError('Duplicate review identities require review')
    if {identity(r) for r in review} != set(by_identity):
        raise ValueError('Review and bibliography identities do not match')
    output_dir.mkdir(parents=True, exist_ok=True)
    audit = []
    for r in review:
        row = {**by_identity[identity(r)], **r}
        disposition, action = recommendation(row)
        audit.append({**row, 'recommendation': disposition, 'next_action': action,
                      'publication_approved': 'false'})
    candidates = [r for r in audit if r['recommendation'] not in {'suppressed_existing_alex', 'excluded_editorial_rejection'}]
    suppressed = [r for r in audit if r['recommendation'] == 'suppressed_existing_alex']
    excluded = [r for r in audit if r['recommendation'] == 'excluded_editorial_rejection']
    approved = [r for r in candidates if r['recommendation'] == 'editorially_approved_pending_release']
    holds = [r for r in candidates if r not in approved]
    fields = list(audit[0])
    for name, rows in [('apwg_recommendation_audit.csv', audit),
                       ('apwg_additions_review.csv', candidates),
                       ('apwg_approved_pending_release.csv', approved),
                       ('apwg_hold_worklist.csv', holds),
                       ('apwg_suppressed_existing.csv', suppressed),
                       ('apwg_excluded_editorial.csv', excluded)]:
        write_csv(output_dir / name, rows, fields)
    artifact_dois = {identity(r)[0] for r in review}
    missing = sorted(doi for doi, e in decisions().items()
                     if e.get('selection_approved') and doi not in artifact_dois)
    summary = {'records_audited': len(audit), 'candidate_additions': len(candidates),
               'suppressed_existing': len(suppressed), 'editorial_rejections': len(excluded), 'approved_pending_release': len(approved),
               'holds': len(holds), 'dispositions': dict(Counter(r['recommendation'] for r in audit)),
               'manifest_approvals_absent_from_artifact': missing,
               'publication_approvals': 0, 'corpus_modified': False}
    (output_dir / 'apwg_recommendation_summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    return summary


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--review', type=Path, required=True)
    p.add_argument('--bibliography', type=Path, required=True)
    p.add_argument('--output-dir', type=Path, required=True)
    a = p.parse_args()
    print(json.dumps(build(a.review, a.bibliography, a.output_dir), indent=2))


if __name__ == '__main__':
    main()

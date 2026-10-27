"""Apply verified, submitted GUI decisions to the SOUPS manifest; never imports papers.

Input: rows read from the owner-private Sites review_decisions table, or a JSON
object with a rows list. Draft rows are not accepted. Every batch is validated
as a whole against current candidate content before any of its decisions apply.
"""
from __future__ import annotations
import argparse
import copy
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from alex.pipelines.soups_review import digest


def batch_number(number):
    if number <= 100:
        return (number + 19) // 20
    return 6 if number <= 118 else 7 + (number - 119) // 20


def apply_submissions(manifest, rows):
    result = copy.deepcopy(manifest)
    indexed = {r['candidate_id']: r for r in result['records'] if r.get('review_number')}
    grouped = defaultdict(list)
    for row in rows:
        if row.get('collection', 'soups') != 'soups':
            continue
        if not isinstance(row.get('revision'), int) or row['revision'] < 1:
            raise ValueError('Only final submitted decision rows are accepted')
        grouped[(row['batch'], row['revision'], row['submission_id'])].append(row)
    latest = {}
    for key in grouped:
        batch, revision, receipt = key
        if batch not in latest or revision > latest[batch][1]:
            latest[batch] = key
        elif revision == latest[batch][1] and receipt != latest[batch][2]:
            raise ValueError('Conflicting receipts for the same batch revision')
    audit = []
    for batch, key in sorted(latest.items()):
        selected = grouped[key]
        expected = {cid for cid, r in indexed.items() if batch_number(r['review_number']) == batch}
        if {r['candidate_id'] for r in selected} != expected or len(selected) != len(expected):
            raise ValueError(f'Incomplete or repeated decision rows for batch {batch}')
        owners = {r.get('user_id') for r in selected}
        if len(owners) != 1 or not next(iter(owners)):
            raise ValueError('Submission must have one authenticated reviewer')
        for row in selected:
            paper = indexed[row['candidate_id']]
            if row['decision'] not in ('approved', 'rejected'):
                raise ValueError('Unknown final decision')
            if row['content_sha256'] != digest(paper) or row['review_number'] != paper['review_number']:
                raise ValueError(f"Paper {paper['review_number']} changed since review; reconcile before applying batch {batch}")
            datetime.fromisoformat(row['created_at'].replace('Z', '+00:00'))
        for row in selected:
            paper = indexed[row['candidate_id']]
            previous = paper.get('gui_submission_revision', 0)
            if previous > row['revision']:
                continue
            if previous == row['revision'] and paper.get('gui_submission_id') != row['submission_id']:
                raise ValueError('Receipt conflicts with a previously applied revision')
            created = datetime.fromisoformat(row['created_at'].replace('Z', '+00:00'))
            paper.update(decision=row['decision'], decision_date=created.astimezone(ZoneInfo('America/Toronto')).date().isoformat(),
                         decision_content_sha256=row['content_sha256'],
                         decision_basis='User submitted ALEX Research Review batch ' + str(batch) + '; receipt ' + row['submission_id'],
                         gui_submission_id=row['submission_id'], gui_submission_revision=row['revision'], publication_approved=False)
        audit.append({'batch': batch, 'revision': key[1], 'receipt': key[2], 'papers': len(selected)})
    result['approved_candidates'] = sum(r.get('decision') == 'approved' for r in result['records'])
    result['rejected_candidates'] = sum(r.get('decision') == 'rejected' for r in result['records'])
    return result, audit


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('submissions', type=Path)
    parser.add_argument('--manifest', type=Path, default=Path('config/soups_review_manifest.json'))
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    incoming = json.loads(args.submissions.read_text())
    result, audit = apply_submissions(json.loads(args.manifest.read_text()), incoming.get('rows', []) if isinstance(incoming, dict) else incoming)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'applied_submissions': audit, 'approved': result['approved_candidates'], 'rejected': result['rejected_candidates']}))


if __name__ == '__main__':
    main()

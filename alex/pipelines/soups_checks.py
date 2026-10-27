"""Audit selected SOUPS papers with the unchanged ALEX quality policy; no import."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from alex.pipelines.apwg_quality_review import assess, load_policy
from alex.pipelines.soups_review import digest
from alex.utils.text import clean


def audit_selected(manifest: dict, link_checks: list[dict]) -> dict:
    policy = load_policy()
    links = {r['candidate_id']:r for r in link_checks}
    results = []
    for row in manifest['records']:
        if row.get('decision') != 'approved':
            continue
        issues = []
        for key in ('title', 'authors', 'year', 'venue', 'publisher', 'abstract', 'source_url'):
            value = clean(row.get(key))
            if not value or any(ord(c) < 32 or 0xe000 <= ord(c) <= 0xf8ff or c == '\ufffd' for c in value):
                issues.append('metadata_or_text_defect:'+key)
        if row.get('decision_content_sha256') != digest(row):
            issues.append('changed_reviewed_content')
        if row.get('publication_year_conflict'):
            issues.append('publication_year_conflict')
        if 'review_required' in row.get('abstract_text_status', ''):
            issues.append('abstract_formatting_review_required')
        if row.get('duplicate_check', {}).get('status') != 'no_match_found':
            issues.append('duplicate_check_hold')
        check = links.get(row['candidate_id'], {})
        effective = check.get('retry', check)
        if effective.get('status') != 200 or 'application/pdf' not in effective.get('content_type', ''):
            issues.append('pdf_link_not_verified')
        quality = assess(row, policy)
        results.append(dict(candidate_id=row['candidate_id'], review_number=row['review_number'],
                            title=row['title'], content_sha256=digest(row),
                            mechanical_status='pass_checked_metadata_and_pdf_link' if not issues else 'hold',
                            mechanical_issues=issues, identifier_status='doi_verified' if row.get('doi') else 'official_URL_verified; DOI_discovery_pending',
                            proposed_category=row.get('proposed_category', ''),
                            proposed_investigation_type=row.get('proposed_investigation_type', ''),
                            publication_approved=False, **quality))
    results.sort(key=lambda r:r['review_number'])
    from collections import Counter
    return dict(schema_version=1, selected_records=len(results), publication_approved=False,
                mechanical_statuses=dict(Counter(r['mechanical_status'] for r in results)),
                quality_statuses=dict(Counter(r['quality_review_status'] for r in results)),
                policy_basis='Unchanged main-branch ALEX policy; unknown citations have zero provisional contribution; no quality exceptions authorized',
                remaining_checks=['DOI discovery, classification review, and quality holds remain open.',
                                  'HTTP PDF links were checked; full PDF contents of the modern selected batch were not audited.'],
                records=results)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, default=Path('config/soups_review_manifest.json'))
    p.add_argument('--links', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    report = audit_selected(json.loads(a.manifest.read_text()), json.loads(a.links.read_text()))
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k != 'records'}, indent=2))


if __name__ == '__main__':
    main()

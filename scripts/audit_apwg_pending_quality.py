"""Offline audit of the pending APWG selections; never changes policy or corpus.

Run from the repository root with PYTHONPATH=.; input is a downloaded review
artifact's apwg_bibliography_with_abstracts.csv, not live provider metadata.
"""
import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from alex.pipelines.apwg_classification_review import review_row
from alex.pipelines.apwg_editorial_review import decision_for, abstract_digest
from alex.pipelines.apwg_import import _verified_corrections, _apply_verified_venue
from alex.pipelines.apwg_import_recommendation import identity, recommendation
from alex.pipelines.apwg_quality_review import load_policy
from alex.utils.scoring import query_keywords
from alex.utils.io import root_file, load_json


def audit(source, run, artifact):
    pending = load_json(root_file('config', 'apwg_pending_review.json'))
    with source.open(newline='', encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    if len({identity(r) for r in rows}) != len(rows):
        raise ValueError('Duplicate source identities')
    wanted = {identity(r) for r in pending['records']}
    selected = [r for r in rows if identity(r) in wanted]
    if len(selected) != len(wanted):
        raise ValueError('Pending records missing or identity changed')
    policy = load_policy()
    keywords = query_keywords(policy[1]['queries'])
    results = []
    corrections = _verified_corrections()
    for row in selected:
        original_venue = row.get("venue", "")
        for correction in corrections.values():
            row = _apply_verified_venue(row, correction)
        entry, status = decision_for(row)
        if status != 'approved':
            raise ValueError('Pending approval identity/content drift: ' + row['title'])
        def no_model(_):
            raise AssertionError('Offline audit must not call a model')
        reviewed = review_row(row, classifier=no_model, policy=policy)
        disposition, action = recommendation(reviewed)
        text = (reviewed['title'] + ' ' + reviewed['abstract']).lower()
        blockers = []
        if not reviewed['abstract']: blockers.append('missing_abstract')
        if reviewed['quality_core_term_gate'] != 'pass': blockers.append('core_term_gate')
        if reviewed['quality_relevance_gate'] != 'pass': blockers.append('relevance_floor')
        if float(reviewed['quality_score']) < float(reviewed['quality_review_threshold']):
            blockers.append('below_review_threshold')
        missing = [k for k in ('doi', 'authors', 'year', 'venue', 'abstract') if not row.get(k)]
        if missing: blockers.append('missing_metadata')
        if str(row.get('requires_bibliographic_review')).lower() == 'true':
            blockers.append('bibliographic_review_flag')
        if row.get('publication_year_conflict'): blockers.append('publication_year_conflict')
        results.append(dict(
            review_number=entry['review_number'], title=row['title'], doi=row['doi'],
            year=row['year'], category=entry['category'], investigation_type=entry['investigation_type'],
            disposition=disposition, next_action=action, blockers=blockers, missing_fields=missing,
            **{k: reviewed[k] for k in reviewed if k.startswith('quality_')},
            matched_core_terms=[t for t in policy[1]['core_keywords'] if t.lower() in text],
            matched_relevance_tokens=sorted(k for k in keywords if k in text),
            abstract_sha256=abstract_digest(reviewed['abstract']), abstract_source=row['abstract_source'],
            citation_count=row['citation_count'], citation_count_source=row['citation_count_source'],
            citation_snapshot_created_at=row.get('citation_snapshot_created_at', ''),
            original_artifact_venue=original_venue, venue_restored=original_venue != row['venue'],
            venue=row['venue'], venue_evidence_url=row.get('venue_evidence_url', ''),
            publication_approved=False))
    results.sort(key=lambda r: r['review_number'])
    return dict(
        source_run=run, source_artifact=artifact, source_file_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
        manifest_sha256=hashlib.sha256(root_file('config', 'apwg_editorial_decisions.json').read_bytes()).hexdigest(),
        policy_sha256={name: hashlib.sha256(root_file('config', name).read_bytes()).hexdigest()
                       for name in ('quality_weights.json', 'query_registry.json', 'venue_whitelist.json')},
        assessment_year=datetime.now(timezone.utc).year, records=len(results),
        dispositions=dict(Counter(r['disposition'] for r in results)),
        overlapping_blockers=dict(Counter(b for r in results for b in r['blockers'])),
        ready_review_numbers=[r['review_number'] for r in results if r['disposition']=='editorially_approved_pending_release'],
        missing_citations=[r['review_number'] for r in results if not r['citation_count']],
        source_total_records=len(rows), source_total_abstracts=sum(bool(r['abstract']) for r in rows),
        source_existing_records=sum(str(r.get('in_existing_alex_corpus')).lower()=='true' for r in rows),
        venue_corrections_sha256=hashlib.sha256(root_file('config', 'apwg_verified_corrections.json').read_bytes()).hexdigest(),
        publication_approved=False, corpus_modified=False, provider_requests=0, model_requests=0, papers=results)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--input', type=Path, required=True)
    p.add_argument('--source-run', type=int, required=True)
    p.add_argument('--source-artifact', type=int, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    result = audit(a.input, a.source_run, a.source_artifact)
    a.output.write_text(json.dumps(result, indent=2, ensure_ascii=False)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k!='papers'}, indent=2))

"""Replay batch 10 from the source manifest, verified official abstracts and assessments.

Usage: python3 scripts/prepare_review_batch_10.py BASE OFFICIAL BASELINE OUTPUT
The caller must reconcile BASE against the current GitHub blob SHA before publishing.
No publication, quality override or editorial decision is granted here.
"""
import hashlib
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def norm(value):
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9]+', ' ', str(value or '').lower())).strip()


def url(value):
    p = urlsplit(value or '')
    return urlunsplit(('https', p.netloc.lower().removeprefix('www.'), p.path.rstrip('/'), p.query, ''))


def doi(value):
    return re.sub(r'^https?://(?:dx\.)?doi.org/', '', str(value or '').strip().lower())


def digest(row):
    fields = ('title', 'authors', 'year', 'doi', 'source_url', 'abstract', 'document_type')
    return hashlib.sha256(json.dumps({k:row.get(k, '') for k in fields}, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def build(base, official, baseline, assessments, baseline_sha256):
    result = json.loads(json.dumps(base))
    rows = {r['candidate_id']:r for r in result['records']}
    old_numbered = {r['candidate_id']:r for r in base['records'] if isinstance(r.get('review_number'), int)}
    if max(r['review_number'] for r in old_numbered.values()) != 178:
        raise ValueError('Review numbering changed; reconcile the current queue first')
    evidence = {r['number']:r for r in official}
    for a in assessments['records']:
        e = evidence[a['review_number']]
        r = rows[e['candidate_id']]
        if r.get('review_number') or r.get('decision') not in ('pending', None) or r['screening_status'] != 'not_assessed':
            raise ValueError('Candidate already reviewed or changed: '+r['candidate_id'])
        meta = e['meta']
        title = meta['citation_title'][0].replace('{', '').replace('}', '')
        if norm(title) != norm(r['title']) or int(meta['citation_publication_date'][0][:4]) != r['year'] or e['source_url'] != r['source_url']:
            raise ValueError('Official evidence identity mismatch')
        r.update(title=title, authors='; '.join(meta['citation_author']), abstract=e['abstract'],
                 abstract_source=r['source_url'], pdf_url=meta['citation_pdf_url'][0],
                 venue=meta['citation_conference_title'][0], publisher='USENIX Association',
                 doi=meta.get('citation_doi', [r.get('doi', '')])[0],
                 metadata_status='official_individual_citation_verified; remaining_checks_pending',
                 source_html_sha256=e['source_sha256'], review_number=a['review_number'],
                 recommendation=a['recommendation'], relevance=a['relevance'],
                 review_reason=a['review_reason'], metadata_issue=a['limitation']+' Official abstract assessed; full paper, DOI lookup, citations and quality checks remain pending.',
                 assessment_basis=assessments['assessment_basis'], assessment_date=assessments['reviewed_at'],
                 review_evidence=[r['source_url']], screening_status='abstract_review_complete',
                 abstract_text_status='official_individual_HTML_abstract_checked',
                 decision='pending', publication_approved=False, full_paper_reviewed=False,
                 quality_status='not_run', classification_status='not_proposed',
                 doi_discovery_status='verified' if meta.get('citation_doi') else 'pending',
                 citation_count=None, citation_status='not_looked_up')
        exact, possible = [], []
        for old in baseline:
            old_urls = [url(old.get(k)) for k in ('source_url', 'Harvest_Source_URL', 'apwg_source_url', 'link') if old.get(k)]
            match = {k:old.get(k, '') for k in ('title', 'year', 'doi', 'source_url')}
            if norm(r['title']) == norm(old.get('title')) or (doi(r.get('doi')) and doi(r['doi']) == doi(old.get('doi'))) or url(r['source_url']) in old_urls:
                exact.append(match)
            elif norm(old.get('title')):
                m = SequenceMatcher(None, norm(r['title']), norm(old['title']))
                if m.real_quick_ratio() >= .90 and m.quick_ratio() >= .90 and m.ratio() >= .90:
                    possible.append(match)
        r['duplicate_check'] = dict(status='existing_match' if exact else 'possible_variant_hold' if possible else 'no_match_found', matches=exact or possible, doi_check='performed' if r['doi'] else 'pending_missing_doi')
        r['dedupe_evidence'] = dict(source_url='https://raw.githubusercontent.com/RISEInfoSec/Alex/main/data/papers.json', corpus_sha256=baseline_sha256, corpus_records=len(baseline), date='2026-10-27', scope='DOI when supplied, normalized title, canonical URL, fuzzy title threshold 0.90; missing DOI and alternate versions remain limitations')
        r['content_sha256'] = digest(r)
    assert all(rows[k] == v for k,v in old_numbered.items()), 'Earlier decisions or content changed'
    result['reviewed_candidates'] = sum(isinstance(r.get('review_number'), int) for r in rows.values())
    result['approved_candidates'] = sum(r.get('decision') == 'approved' for r in rows.values())
    result['rejected_candidates'] = sum(r.get('decision') == 'rejected' for r in rows.values())
    result['substantive_abstract_assessments'] = base['substantive_abstract_assessments'] + 20
    result['publication_approved'] = False
    result['review_order'] = 'Continue substantive source screening and prepare review batches; preserve existing acceptance and publication policies. Accepted content may enter mechanical assessments without waiting for all source screening.'
    result['latest_prepared_batch'] = dict(batch=10, first=179, last=198, pending=20, assessed_at='2026-10-27', evidence_basis=assessments['assessment_basis'])
    return result


if __name__ == '__main__':
    base, official, baseline = [json.loads(Path(p).read_text()) for p in sys.argv[1:4]]
    assessments = json.loads((Path(__file__).resolve().parents[1]/'config/soups_review_batch_10_assessments.json').read_text())
    result = build(base, official, baseline, assessments, hashlib.sha256(Path(sys.argv[3]).read_bytes()).hexdigest())
    Path(sys.argv[4]).write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    new = [r for r in result['records'] if 179 <= r.get('review_number', 0) <= 198]
    print(json.dumps(dict(new_candidates=len(new), duplicate_checks={r['review_number']:r['duplicate_check']['status'] for r in new}, prior_decisions_preserved=True)))


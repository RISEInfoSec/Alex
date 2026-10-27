"""Review-only SOUPS inventory. Never writes the public corpus or grants approval.

Replay: python -m alex.pipelines.soups_review --snapshots .cache/soups
Acquisition: node scripts/soups_fetch.mjs .cache/soups
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup
from alex.utils.text import clean, normalize_title
from alex.pipelines.soups_evidence import restore_evidence

LABEL = "SOUPS (Symposium On Usable Privacy and Security) and USENIX (the Advanced Computing Systems Association)"
COLLECTION_LINKS = (
    {'name': 'SOUPS', 'url': 'https://soups.page/'},
    {'name': 'USENIX', 'url': 'https://www.usenix.org/'},
)


def attribution_fields() -> dict:
    return {'collection_source': LABEL, 'collection_url': COLLECTION_LINKS[0]['url'],
            'collection_links': [dict(link) for link in COLLECTION_LINKS]}


def canonical_url(url: str) -> str:
    p = urlsplit(url)
    return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip('/'), p.query, ''))


def identity(url: str) -> str:
    return 'soups-' + hashlib.sha256(canonical_url(url).encode()).hexdigest()[:20]


def digest(row: dict) -> str:
    content = {k: row.get(k, '') for k in ('title', 'authors', 'year', 'doi', 'source_url', 'abstract', 'document_type')}
    return hashlib.sha256(json.dumps(content, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def usenix_records(html: str, year: int, url: str) -> list[dict]:
    soup = BeautifulSoup(html, 'html.parser')
    out = []
    for node in soup.select('.node-paper'):
        heading = node.find('h2')
        link = heading.find('a', href=True) if heading else None
        if not link:
            continue
        byline = node.select_one('.field-name-field-paper-people-text')
        description = node.select_one('.field-name-field-paper-description-long')
        raw = clean(byline.get_text(' ', strip=True)) if byline else ''
        # Affiliations are explicitly marked as emphasis in USENIX bylines.
        names = BeautifulSoup(str(byline), 'html.parser')
        for affiliation in names.select('em'):
            affiliation.decompose()
        authors = clean(names.get_text(' ', strip=True)).strip(' ,;') if byline else ''
        authors = re.sub(r'\s*,\s*;', ';', authors)
        authors = re.sub(r';\s*;', ';', authors)
        source = urljoin(url, link['href'])
        session = node.find_parent(class_='node-session')
        session_heading = session.find('h2') if session else None
        session_name = clean(session_heading.get_text(' ', strip=True)) if session_heading else ''
        non_paper = bool(re.search(r'\b(lightning|keynote|tutorial|invited|poster|workshop)\b', session_name, re.I)
                         or re.match(r'^Lightning Talks?\b', clean(link.get_text()), re.I))
        out.append(dict(
            candidate_id=identity(source), title=clean(link.get_text(' ', strip=True)),
            authors=authors, author_byline=raw, year=year, conference_year=year,
            source_url=source, discovery_url=url, doi='',
            document_type='research_paper' if byline and not non_paper else 'invited_talk_or_other_program_item',
            program_session=session_name,
            abstract=clean(description.get_text(' ', strip=True)) if description else '',
            abstract_source=url if description else '',
            metadata_status='annual_program_metadata; individual_bibliography_pending',
            **attribution_fields(), publication_approved=False,
        ))
    return out


def legacy_records(html: str, year: int, url: str) -> list[dict]:
    soup = BeautifulSoup(html, 'html.parser')
    out, seen = [], set()
    for link in soup.select('a[href]'):
        target = urljoin(url, link['href'])
        title = clean(link.get_text(' ', strip=True))
        path = urlsplit(target).path.lower()
        proceeding = 'proceedings/' in path or '2005proceedings/' in path
        # Some official 2012 paper links omit the file extension. Preserve them
        # as printed, with link verification pending; never synthesize a PDF URL.
        if not (path.endswith('.pdf') or proceeding) or len(title) < 18:
            continue
        if '/slides/' in path or 'slides' in title.lower():
            continue
        section = link.find_previous('h2')
        section_title = clean(section.get_text(' ', strip=True)).lower() if section else ''
        if 'front-matter' in path or 'front matter' in title.lower():
            kind = 'proceedings_front_matter'
        elif 'poster' in section_title or 'poster' in path:
            kind = 'poster_or_poster_showcase'
        elif proceeding:
            kind = 'research_paper'
        else:
            kind = 'other_linked_document'
        if canonical_url(target) in seen:
            continue
        seen.add(canonical_url(target))
        parent = link.find_parent(['li', 'p'])
        byline = clean(parent.get_text(' ', strip=True)) if parent else ''
        out.append(dict(
            candidate_id=identity(target), title=title, authors='', author_byline=byline,
            year=year, conference_year=year, source_url=target, discovery_url=url,
            doi='', document_type=kind, abstract='', abstract_source='',
            metadata_status='program_title_only; authors_and_abstract_require_verification',
            **attribution_fields(), publication_approved=False,
        ))
    return out


def duplicate_check(row: dict, corpus: list[dict]) -> dict:
    def doi(v):
        return re.sub(r'^https?://(?:dx\.)?doi.org/', '', clean(v).lower())
    title, d, u = normalize_title(row['title']), doi(row.get('doi')), canonical_url(row['source_url'])
    exact, possible = [], []
    for old in corpus:
        if '_soups_dedupe' not in old:
            old['_soups_dedupe'] = (normalize_title(old.get('title', '')), doi(old.get('doi')),
                                    [canonical_url(old[k]) for k in ('source_url', 'Harvest_Source_URL', 'apwg_source_url') if old.get(k)])
        ot, od, urls = old['_soups_dedupe']
        if title == ot or (d and d == od) or u in urls:
            exact.append({'title': old['title'], 'doi': old.get('doi', ''), 'source_url': old.get('source_url', '')})
        elif ot:
            matcher = SequenceMatcher(None, title, ot)
            if matcher.real_quick_ratio() >= .90 and matcher.quick_ratio() >= .90 and matcher.ratio() >= .90:
                possible.append({'title': old['title'], 'doi': old.get('doi', ''), 'source_url': old.get('source_url', '')})
    return {'status': 'existing_match' if exact else 'possible_variant_hold' if possible else 'no_match_found',
            'matches': exact or possible, 'doi_check': 'performed' if d else 'pending_missing_doi'}


def enrich_presentation(row: dict, html: str, url: str) -> dict:
    soup = BeautifulSoup(html, 'html.parser')
    meta = {}
    for element in soup.select('meta[name^="citation_"]'):
        meta.setdefault(element.get('name'), []).append(clean(element.get('content')))
    def first(key):
        return next(iter(meta.get('citation_'+key, [])), '')
    title = first('title').replace('{', '').replace('}', '')
    if normalize_title(title) != normalize_title(row['title']):
        raise ValueError('Individual paper title mismatch: '+url)
    year = first('publication_date')[:4]
    if year != str(row['year']):
        raise ValueError('Individual paper publication year conflict: '+url)
    authors = meta.get('citation_author', [])
    if not authors or not first('conference_title'):
        raise ValueError('Incomplete individual bibliography: '+url)
    bib = soup.get_text(' ', strip=True)
    publisher = re.search(r'publisher\s*=\s*\{([^}]+)\}', bib)
    return {**row, 'authors': '; '.join(authors), 'venue': first('conference_title'),
            'publisher': publisher.group(1) if publisher else '', 'doi': first('doi'),
            'pdf_url': first('pdf_url'), 'bibliographic_evidence': url,
            'metadata_status': 'official_individual_citation_verified; DOI_not_supplied' if not first('doi') else 'official_individual_citation_verified'}


def merge_state(rows: list[dict], previous: dict) -> list[dict]:
    old = {r['candidate_id']: r for r in previous.get('records', [])}
    for row in rows:
        row['content_sha256'] = digest(row)
        prior = old.pop(row['candidate_id'], {})
        for key in ('review_number', 'recommendation', 'relevance', 'review_reason', 'review_evidence',
                    'proposed_category', 'proposed_investigation_type', 'decision_basis',
                    'decision_date', 'decision_content_sha256', 'previous_decision',
                    'previous_decision_content_sha256', 'abstract_text_status', 'classification_status'):
            if key in prior:
                row[key] = prior[key]
        row['decision'] = prior.get('decision', 'pending')
        row['screening_status'] = prior.get('screening_status', 'not_assessed')
        if prior and prior.get('content_sha256') != row['content_sha256']:
            row['previous_decision'] = row['decision']
            row['previous_decision_content_sha256'] = prior.get('decision_content_sha256', '')
            row['decision'] = 'pending_content_changed'
            row['screening_status'] = 'needs_reassessment'
        row['publication_approved'] = False
    # A source disappearing on refresh must not erase its identity or decisions.
    return rows + [{**r, 'source_missing_on_refresh': True, 'publication_approved': False} for r in old.values()]


def build(snapshots: Path, corpus_path: Path, output: Path, base_commit: str = '') -> dict:
    fetches = json.loads((snapshots / 'fetch-log.json').read_text())
    log = {r['key']: r for r in fetches}
    all_rows, coverage = [], []
    last_year = max([2013] + [int(key[5:]) for key in log if re.fullmatch(r'year-20\d\d', key)])
    historical = snapshots/'legacy-home-2013.html'
    historical_text = BeautifulSoup(historical.read_text(), 'html.parser').get_text(' ', strip=True) if historical.exists() else ''
    historical_counts = {int(y):int(n) for y,n in re.findall(r'(20\d\d)\s*:\s*(\d+)\s*/\s*\d+', historical_text)}
    for year in range(2005, last_year+1):
        key = f'program-{year}' if year < 2014 else f'year-{year}'
        receipt = log.get(key, {})
        path = snapshots / (key + '.html')
        rows = []
        if receipt.get('status') == 200 and path.exists():
            parser = legacy_records if year < 2014 else usenix_records
            rows = parser(path.read_text(), year, receipt['final_url'])
        full = [r for r in rows if r['document_type'] == 'research_paper']
        coverage.append(dict(year=year, source_url=receipt.get('final_url', ''), http_status=receipt.get('status'),
                             research_papers=len(full), other_program_documents=len(rows)-len(full),
                             abstracts=sum(bool(r['abstract']) for r in full),
                             discovery_status='annual_page_parsed_not_independently_reconciled' if rows else 'gap',
                             relevance_status='partial_or_not_assessed',
                             ancillary_coverage='partial; linked sources inventoried separately'))
        if year in historical_counts:
            coverage[-1]['historical_accepted_tally'] = historical_counts[year]
            if historical_counts[year] != len(full):
                coverage[-1]['reconciliation_note'] = 'Historical acceptance tally differs from linked program papers; unresolved.'
        all_rows.extend(rows)
    with corpus_path.open(encoding='utf-8', newline='') as f:
        corpus = list(csv.DictReader(f))
    details = {canonical_url(r.get('final_url', '')): r for r in fetches
               if r.get('status') == 200 and r['key'].startswith('paper-')}
    for row in all_rows:
        row.update(restore_evidence(row, corpus_path.parent.parent/'config'))
        detail = details.get(canonical_url(row['source_url']))
        if detail:
            row.update(enrich_presentation(row, (snapshots/(detail['key']+'.html')).read_text(), row['source_url']))
        row['duplicate_check'] = duplicate_check(row, corpus)
    previous = json.loads(output.read_text()) if output.exists() else {}
    records = merge_state(all_rows, previous)
    if len({r['candidate_id'] for r in records}) != len(records):
        raise ValueError('Duplicate source identity in inventory')
    result = dict(schema_version=1, base_commit=base_commit,
                  baseline_corpus_sha256=hashlib.sha256(corpus_path.read_bytes()).hexdigest(),
                  existing_corpus_records=len(corpus), **attribution_fields(),
                  publication_approved=False, annual_coverage=coverage, records=records)
    result['initial_inventory_research_papers'] = sum(c['research_papers'] for c in coverage)
    result['initial_inventory_other_documents'] = sum(c['other_program_documents'] for c in coverage)
    result['reviewed_candidates'] = sum(bool(r.get('review_number')) for r in records)
    result['approved_candidates'] = sum(r.get('decision') == 'approved' for r in records)
    result['rejected_candidates'] = sum(r.get('decision') == 'rejected' for r in records)
    result['substantive_abstract_assessments'] = sum(r.get('screening_status', 'not_assessed') != 'not_assessed' for r in records)
    result['dedup_limitations'] = ['Missing DOIs and alternate-title versions require follow-up; no-match is not proof of uniqueness.']
    for entry in coverage:
        count = sum(bool(r.get('review_number')) and r['year'] == entry['year'] for r in records)
        entry['relevance_status'] = f'{count} reviewed candidates; remaining records not assessed'
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    return result


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--snapshots', type=Path, default=Path('.cache/soups'))
    p.add_argument('--corpus', type=Path, default=Path('data/accepted_classified.csv'))
    p.add_argument('--output', type=Path, default=Path('config/soups_review_manifest.json'))
    p.add_argument('--base-commit', default='', help='Verified GitHub baseline, if known')
    a = p.parse_args()
    result = build(a.snapshots, a.corpus, a.output, a.base_commit)
    print(json.dumps({'records':len(result['records']), 'annual_coverage':result['annual_coverage']}, indent=2))


if __name__ == '__main__':
    main()

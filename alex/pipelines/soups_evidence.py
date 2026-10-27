"""Content-bound, review-only SOUPS bibliography and abstract checkpoints."""
from __future__ import annotations

import json
import re
from pathlib import Path
from alex.utils.text import clean, normalize_title


def openalex_citation_match(items: list[dict], row: dict) -> tuple[dict | None, str]:
    """Identify one version; never sum duplicates or replace the conference DOI."""
    expected = {normalize_title(a) for a in row['authors'].split(';') if clean(a)}
    matches = []
    for item in items:
        actual = {normalize_title(a.get('author', {}).get('display_name', '')) for a in item.get('authorships', [])}
        overlap = expected & actual
        if (normalize_title(item.get('title', '')) == normalize_title(row['title']) and
                item.get('publication_year') == row['year'] and expected and
                len(overlap) >= min(2, len(expected))):
            matches.append((item, len(overlap)))
    if len(matches) != 1:
        return None, 'ambiguous_author_matched_versions' if matches else 'no_exact_title_year_and_author_match'
    item, count = matches[0]
    value = item.get('cited_by_count')
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        return None, 'invalid_citation_count'
    return dict(citation_count=value, citation_work_url=item['id'],
                citation_version_doi=item.get('doi') or '', matched_author_count=count), 'verified_version'


def crossref_matches(items: list[dict], rows: list[dict]) -> list[dict]:
    """Require a SOUPS venue and exact full title, including deposited subtitle.

    Conflicting years are retained as holds, never overwritten. Similar titles
    are not accepted. Returned records remain bibliographic proposals.
    """
    index = {}
    for item in items:
        if not re.search(r'usable privacy.*security', ' '.join(item.get('container-title', [])), re.I):
            continue
        for title in item.get('title', []):
            variants = [title] + [title+': '+s for s in item.get('subtitle', [])]
            for variant in variants:
                index.setdefault(normalize_title(variant), []).append(item)
    result = []
    for row in rows:
        matches = {item['DOI']:item for item in index.get(normalize_title(row['title']), []) if item.get('DOI')}
        if len(matches) != 1:
            continue
        item = next(iter(matches.values()))
        authors = [' '.join([a.get('given', ''), a.get('family', '')]).strip() for a in item.get('author', [])]
        year = item.get('published', {}).get('date-parts', [[None]])[0][0]
        if not authors or not year:
            continue
        result.append(dict(candidate_id=row['candidate_id'], title=row['title'],
                           source_url=row['source_url'], conference_year=row['conference_year'],
                           doi=item['DOI'], authors='; '.join(authors),
                           venue='; '.join(item.get('container-title', [])), publisher=item.get('publisher', ''),
                           crossref_year=year, bibliographic_evidence='https://api.crossref.org/works/'+item['DOI'],
                           publication_year_conflict='' if year == row['year'] else f"program={row['year']}; Crossref={year}"))
    return result


def restore_evidence(row: dict, directory: Path) -> dict:
    """Apply identity-bound verified evidence; never infer or grant approval."""
    row = dict(row)
    for name, fields in [
        ('soups_bibliographic_evidence.json', ('doi', 'authors', 'venue', 'publisher', 'crossref_year',
                                              'bibliographic_evidence', 'publication_year_conflict')),
        ('soups_abstract_evidence.json', ('abstract', 'abstract_source', 'pdf_sha256', 'abstract_text_status')),
        ('soups_citation_evidence.json', ('citation_count', 'citation_count_source', 'citation_work_url',
                                         'citation_version_doi', 'citation_snapshot_created_at')),
    ]:
        path = directory/name
        if not path.exists():
            continue
        data = json.loads(path.read_text())
        evidence = next((r for r in data['records'] if r['candidate_id'] == row['candidate_id']), None)
        if not evidence:
            continue
        if (normalize_title(evidence['title']) != normalize_title(row['title']) or
                evidence['source_url'] != row['source_url'] or
                evidence['conference_year'] != row['conference_year']):
            raise ValueError('SOUPS evidence identity mismatch: '+row['candidate_id'])
        for field in fields:
            if field in evidence:
                row[field] = evidence[field]
        if 'doi' in fields:
            row['metadata_status'] = ('hold_publication_year_conflict' if row.get('publication_year_conflict')
                                      else 'exact_title_subtitle_and_year_crossref_match')
    row['publication_approved'] = False
    return row


def extract_cached_pdfs(fetch_log: Path, manifest_path: Path, output: Path) -> dict:
    """Read at most three pages, reuse APWG extraction, delete transient PDFs.

    Extracted abstracts retain a formatting-review hold until visually checked.
    Explicit ACM CR Categories are removed at their labelled boundary.
    """
    import logging
    from pypdf import PdfReader
    from alex.pipelines.apwg_pdf_abstracts import extract_abstract, _title_corresponds
    logging.getLogger('pypdf').setLevel(logging.ERROR)
    lookup = {r['candidate_id']:r for r in json.loads(manifest_path.read_text())['records']}
    prior = json.loads(output.read_text()) if output.exists() else {'records':[]}
    records = {r['candidate_id']:r for r in prior['records']}
    for receipt in json.loads(fetch_log.read_text()):
        file = Path(receipt['file']) if receipt.get('file') else None
        if not file or not file.exists():
            continue
        row = lookup[receipt['candidate_id']]
        permitted = manifest_path.resolve().parent.parent/'tmp'/'pdfs'
        if file.resolve().parent != permitted or file.name != row['candidate_id']+'.pdf':
            raise ValueError('PDF path outside task staging directory')
        import hashlib
        if file.stat().st_size > 8*1024*1024 or hashlib.sha256(file.read_bytes()).hexdigest() != receipt['sha256']:
            raise ValueError('Staged PDF size/hash mismatch')
        try:
            pdf = PdfReader(file, strict=False)
            first_page = pdf.pages[0].extract_text() or ''
            text = '\n'.join(page.extract_text() or '' for page in list(pdf.pages)[:3])
            abstract = extract_abstract(text) if _title_corresponds(first_page, row['title']) else ''
            abstract = re.split(r'\bCR Categories\s*:', abstract, flags=re.I)[0].strip()
            if any(ord(c) < 32 or 0xe000 <= ord(c) <= 0xf8ff or c == '\ufffd' for c in abstract):
                abstract = ''
            records[row['candidate_id']] = dict(candidate_id=row['candidate_id'], title=row['title'],
                source_url=row['source_url'], conference_year=row['conference_year'], abstract=abstract,
                abstract_source=row['source_url'], pdf_sha256=receipt['sha256'],
                abstract_text_status='explicit_section_extracted_formatting_review_required' if abstract else 'no_confident_abstract')
        finally:
            file.unlink()
    result = dict(schema_version=1, publication_approved=False, records=list(records.values()))
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    return result


def main():
    import argparse
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation', choices=['bibliography', 'citations', 'abstracts'])
    p.add_argument('--manifest', type=Path, default=Path('config/soups_review_manifest.json'))
    p.add_argument('--snapshots', type=Path, default=Path('.cache/soups'))
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    rows = json.loads(a.manifest.read_text())['records']
    if a.operation == 'abstracts':
        result = extract_cached_pdfs(a.snapshots/'legacy-pdf-fetch.json', a.manifest, a.output)
    else:
        result = dict(schema_version=1, publication_approved=False)
        if a.operation == 'bibliography':
            items = json.loads((a.snapshots/'crossref-historical.json').read_text())['message']['items']
            result['records'] = crossref_matches(items, [r for r in rows if r['year'] < 2014 and r['document_type'] == 'research_paper'])
        else:
            lookup = {r['candidate_id']:r for r in rows}
            records, holds = [], []
            for receipt in json.loads((a.snapshots/'openalex-receipts.json').read_text()):
                row = lookup[receipt['candidate_id']]
                if receipt.get('status') != 200:
                    holds.append(dict(candidate_id=row['candidate_id'], status='upstream_unavailable'))
                    continue
                items = json.loads((a.snapshots/'openalex'/(row['candidate_id']+'.json')).read_text()).get('results', [])
                match, status = openalex_citation_match(items, row)
                if not match:
                    holds.append(dict(candidate_id=row['candidate_id'], title=row['title'], status=status, query_url=receipt['url']))
                    continue
                records.append(dict(candidate_id=row['candidate_id'], title=row['title'], source_url=row['source_url'],
                                    conference_year=row['conference_year'], **match,
                                    citation_count_source='OpenAlex; exact-title/year/author-matched repository version, not a merged conference citation count',
                                    citation_snapshot_created_at=receipt['retrieved_at']))
            result.update(records=records, holds=holds)
        a.output.parent.mkdir(parents=True, exist_ok=True)
        a.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({'records':len(result['records']), 'publication_approved':False}))


if __name__ == '__main__':
    main()

"""Offline discovery of SOUPS posters and workshop material; never approves imports.

Replay against bounded HTML snapshots, preserving document type and version status.
"""
from __future__ import annotations
import argparse
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup
from alex.pipelines.soups_review import attribution_fields, identity, usenix_records, legacy_records
from alex.utils.text import clean


def year_from_url(url):
    match = re.search(r'(?:soups)?(20\d{2})', url)
    return int(match.group(1)) if match else None


def published_section(node):
    for heading in node.find_all_previous(['h2', 'h3']):
        if heading.find_parent(class_='node-paper'):
            continue
        text = heading.get_text(' ', strip=True).lower()
        if 'unpublished' in text or 'novel poster' in text:
            return False
        if 'published work' in text or 'previously published' in text:
            return True
    return None


def row_for(title, source, discovery, year, kind, authors='', **extra):
    return dict(candidate_id=identity(source), title=clean(title), authors=authors,
                year=year, conference_year=year, source_url=source,
                discovery_url=discovery, document_type=kind, doi='', abstract='',
                metadata_status='ancillary_program_only; content_verification_pending',
                decision='pending', publication_approved=False,
                **attribution_fields(), **extra)


def parse_page(html, url):
    soup = BeautifulSoup(html, 'html.parser')
    year = year_from_url(url)
    records = []
    if 'postersproc' in url:
        for authors in soup.select('ul.author-list'):
            item = authors.parent
            link = item.find('a', href=True, recursive=False)
            if not link:
                continue
            names = []
            for byline in authors.find_all('li', recursive=False):
                copy = BeautifulSoup(str(byline), 'html.parser')
                for affiliation in copy.select('em'):
                    affiliation.decompose()
                names.append(clean(copy.get_text(' ', strip=True)).strip(' ,'))
            previous = published_section(item)
            records.append(row_for(link.get_text(' ', strip=True), urljoin(url, link['href']), url, year,
                                   'poster_of_previously_published_work' if previous else 'poster_extended_abstract',
                                   '; '.join(names), previously_published=previous,
                                   publication_year_status='original_venue_year_pending' if previous else 'event_year'))
    elif 'poster-session' in url or '/workshop-program/' in url:
        rows = usenix_records(html, year, url)
        nodes = {}
        for node in soup.select('.node-paper'):
            heading = node.find('h2')
            link = heading.find('a', href=True) if heading else None
            if link:
                nodes[urljoin(url, link['href'])] = node
        for row in rows:
            node = nodes[row['source_url']]
            row['title'] = re.sub(r'^\[#\d+\]\s*', '', row['title'])
            previous = published_section(node) if 'poster-session' in url else None
            row.update(previously_published=previous, decision='pending')
            if 'poster-session' in url:
                row['document_type'] = 'poster_of_previously_published_work' if previous else 'poster_extended_abstract'
            else:
                row['document_type'] = 'workshop_program_item' if re.search(r'keynote|invited|lightning|panel', row.get('program_session', ''), re.I) else 'workshop_paper_or_abstract'
            records.append(row)
        # Earlier USENIX poster lists use paragraphs instead of node-paper.
        if not rows and 'poster-session' in url:
            for paragraph in soup.select('p'):
                title = paragraph.find('strong', recursive=False)
                link = next((a for a in paragraph.select('a[href]') if 'poster description' in a.get_text(' ', strip=True).lower()), None)
                if not title or not link:
                    continue
                byline = BeautifulSoup(str(paragraph), 'html.parser')
                for element in byline.select('strong, em, a'):
                    element.decompose()
                previous = published_section(paragraph)
                records.append(row_for(title.get_text(' ', strip=True), urljoin(url, link['href']), url, year,
                                       'poster_of_previously_published_work' if previous else 'poster_extended_abstract',
                                       clean(byline.get_text(' ', strip=True)).strip(' ,;'), previously_published=previous))
    elif re.search(r'/201[45]/program\.(?:html|php)', url):
        records.extend(r for r in legacy_records(html, year, url) if r['document_type'] == 'poster_or_poster_showcase')
    elif any(x in url for x in ['/usm.html', '/user.html', '/sputter.html', '/hups.html', '/risk.html', '/trustbusters.html', '/mobile.html']):
        for link in soup.select('a[href]'):
            target = urljoin(url, link['href'])
            title = clean(link.get_text(' ', strip=True))
            if not urlsplit(target).path.lower().endswith('.pdf') or len(title) < 18 or re.search(r'call for|template|submission|flyer|full program', title, re.I):
                continue
            records.append(row_for(title, target, url, year, 'workshop_paper_or_abstract'))
    return records


def inventory(directory):
    log = json.loads((directory / 'fetch-log.json').read_text())
    found = {}
    coverage = []
    seen = set()
    for source in log:
        url = source['url'].rstrip('/')
        if url in seen:
            continue
        seen.add(url)
        rows = []
        if source.get('status') == 200 and not source.get('error'):
            rows = parse_page((directory / source['snapshot']).read_text(), source['url'])
        for row in rows:
            if row['candidate_id'] in found:
                found[row['candidate_id']].setdefault('additional_discovery_urls', []).append(row['discovery_url'])
            else:
                found[row['candidate_id']] = row
        coverage.append({**{k: source[k] for k in ['url', 'source_url', 'status', 'error', 'retrieved_at'] if k in source},
                         'parsed_items': len(rows), 'discovery_complete': False,
                         'assessment_status': 'not_assessed'})
    return {'schema_version': 1, 'publication_approved': False,
            'coverage_status': 'partial; poster/workshop item counts are provisional',
            'document_type_counts': dict(Counter(r['document_type'] for r in found.values())),
            'sources': coverage, 'records': list(found.values())}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshots', type=Path, default=Path('.cache/soups/ancillary'))
    parser.add_argument('--output', type=Path, default=Path('config/soups_ancillary_inventory.json'))
    args = parser.parse_args()
    result = inventory(args.snapshots)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'sources': len(result['sources']), 'types': result['document_type_counts']}))


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Isolated CI browser regression for the staged site; never deploys.

Requires Playwright/Chromium in the test runner only. Production generation and
Pages staging remain standard-library Python. Screenshots are review artifacts.
"""
from __future__ import annotations

import argparse
import functools
import http.server
import json
import threading
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET

from playwright.sync_api import sync_playwright


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass


def verify(site: Path, report_dir: Path) -> None:
    site = site.resolve()
    report_dir.mkdir(parents=True, exist_ok=True)
    namespace = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
    urls = [e.text for e in ET.parse(site / 'sitemap.xml').findall('.//sm:loc', namespace)]
    paths = [url.removeprefix('https://alex.riseinfosec.org') for url in urls if '/research/' in url]
    papers = json.loads((site / 'data/papers.json').read_text(encoding='utf-8'))
    expected = {field: Counter(p.get(field, '') for p in papers) for field in ('category', 'investigation_type')}
    server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), functools.partial(QuietHandler, directory=str(site)))
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    results = {'static_pages': len(paths), 'widths': [320, 390, 1440], 'javascript_disabled': True, 'layouts_checked': 0}
    screenshots = {
        ('/research/', 390): 'hub-mobile.png',
        ('/research/', 1440): 'hub-desktop.png',
        ('/research/categories/osint-methodology/', 390): 'category-mobile.png',
        ('/research/investigations/phishing-analysis/', 390): 'investigation-mobile.png',
        ('/research/bibliography/', 390): 'complete-bibliography-mobile.png',
        ('/research/bibliography/page/58/', 390): 'long-metadata-mobile.png',
    }
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch()
            for width in results['widths']:
                context = browser.new_context(viewport={'width': width, 'height': 900}, java_script_enabled=False)
                page = context.new_page()
                for path in paths:
                    response = page.goto(origin + path, wait_until='load')
                    assert response and response.status == 200, path
                    assert page.locator('h1').count() == 1, path
                    assert page.locator('main').count() == 1, path
                    assert page.locator('body').evaluate('(e) => document.documentElement.scrollWidth <= innerWidth'), f'Horizontal overflow: {width}px {path}'
                    assert page.locator('script:not([type="application/ld+json"])').count() == 0, path
                    assert page.locator('img').evaluate_all('(images) => images.every(image => image.hasAttribute("alt") && image.alt.length > 0)'), path
                    assert page.locator('nav[aria-label="Library navigation"] a').count() == 3, path
                    for nav in page.locator('nav[aria-label="Bibliography pages"]').all():
                        assert nav.locator('a').count() <= 8, path
                    if path == '/research/':
                        page.keyboard.press('Tab')
                        assert page.evaluate('document.activeElement.textContent.trim()') == 'Skip to content'
                        page.keyboard.press('Enter')
                        assert page.url.endswith('#main')
                    if (path, width) in screenshots:
                        if path.startswith('/research/bibliography/'):
                            page.get_by_role('link', name='Go to the bibliography', exact=True).click()
                        page.screenshot(path=str(report_dir / screenshots[(path, width)]))
                    results['layouts_checked'] += 1
                # Native HTML pagination remains usable with JavaScript off.
                page.goto(origin + '/research/bibliography/')
                page.get_by_role('link', name='Next', exact=True).first.click()
                assert '/research/bibliography/page/2/' in page.url
                assert page.locator('li.paper').count() == 50
                context.close()

            context = browser.new_context(viewport={'width': 1440, 'height': 1000})
            page = context.new_page()
            errors = []
            requests = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda request: requests.append(request.url))
            page.goto(origin + '/', wait_until='load')
            page.wait_for_function('document.querySelectorAll("#results > .section").length === 5')
            assert len(papers) >= 5
            page.locator('#categoryFilter').select_option(label='OSINT Methodology')
            assert page.locator('#results > .section').count() == expected['category']['OSINT Methodology']
            page.locator('#clearBtn').click()
            page.locator('#investigationFilter').select_option(label='Phishing Analysis')
            assert page.locator('#results > .section').count() == expected['investigation_type']['Phishing Analysis']
            page.locator('#clearBtn').click()
            page.locator('#browseBtn').click()
            assert page.locator('#results > .section').count() == len(papers)
            page.locator('#browseBtn').click()
            assert page.locator('#results > .section').count() == 5
            assert not errors, errors
            assert not any('/research/' in url or '/collections.css' in url for url in requests)
            results['search'] = {'total_papers': len(papers), 'initial_papers': 5, 'errors': errors, 'collection_requests': 0}
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
    (report_dir / 'browser-validation.json').write_text(json.dumps(results, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(results))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site', type=Path, default=Path('_site'))
    parser.add_argument('--report-dir', type=Path, default=Path('_layout_review'))
    args = parser.parse_args()
    verify(args.site, args.report_dir)

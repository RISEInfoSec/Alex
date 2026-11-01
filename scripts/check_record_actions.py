"""Browser regression checks against the exact staged public artifact."""
import functools
import json
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import sys

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from alex.record_links import public_record_url


def main():
    papers = json.loads((ROOT / '_site/data/papers.json').read_text())
    handler = functools.partial(SimpleHTTPRequestHandler, directory=str(ROOT / '_site'))
    server = ThreadingHTTPServer(('127.0.0.1', 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}'
    output = ROOT / '_layout_review'
    output.mkdir(exist_ok=True)
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            for width in (1440, 390):
                context = browser.new_context(viewport={'width': width, 'height': 900},
                                              permissions=['clipboard-read', 'clipboard-write'])
                context.route('https://riseinfosec.org/**', lambda route: route.abort())
                page = context.new_page()
                errors = []
                page.on('pageerror', lambda error: errors.append(str(error)))
                for paper in (papers[0], next(p for p in papers if not p.get('doi'))):
                    page.goto(base + '/?' + urlsplit(public_record_url(paper)).query)
                    page.get_by_text('Shared ALEX record', exact=True).wait_for()
                    assert page.locator('#results .section').count() == 1
                    assert page.locator('#results h3').inner_text() == paper['title']
                    assert page.locator('#results details').get_attribute('open') is not None
                    assert page.locator('#includeHistorical').is_hidden()
                    assert page.locator('#browseBtn').is_hidden()
                    assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
                    page.get_by_role('button', name='Copy link', exact=True).click()
                    page.get_by_text('Link copied.', exact=True).wait_for()
                    assert page.evaluate('navigator.clipboard.readText()') == public_record_url(paper)
                    flag = page.get_by_role('link', name='Flag for deletion').get_attribute('href')
                    query = parse_qs(urlsplit(flag).query)
                    assert query['record-url'] == [public_record_url(paper)]
                    assert query['record-title'] == [paper['title'].strip()]
                    assert query['template'] == ['record-removal.yml']
                page.locator('.record-actions').scroll_into_view_if_needed()
                page.screenshot(path=str(output / f'record-sharing-{width}.png'))
                page.get_by_role('button', name='Clear filters', exact=True).click()
                assert 'record=' not in page.url
                assert page.locator('#results .section').count() == 5
                page.goto(base + '/?record=doi:missing')
                page.get_by_role('heading', name='Record unavailable', exact=True).wait_for()
                assert page.get_by_role('button', name='Copy link', exact=True).count() == 0
                assert not errors, errors
                context.close()
            context = browser.new_context()
            context.add_init_script("Object.defineProperty(navigator, 'clipboard', {value: {writeText: async () => {throw Error('denied')}}})")
            page = context.new_page()
            page.goto(base + '/?' + urlsplit(public_record_url(papers[0])).query)
            page.get_by_role('button', name='Copy link', exact=True).click()
            fallback = page.get_by_label('Public record link', exact=True)
            assert fallback.input_value() == public_record_url(papers[0])
            assert fallback.is_visible()
            page.get_by_text('Copy the selected link.', exact=True).wait_for()
            # The request generator is independent of clipboard access.
            assert page.get_by_role('link', name='Flag for deletion').get_attribute('href').startswith('https://github.com/RISEInfoSec/Alex/issues/new?')
            context.close()
            # Explicit historical records must open from a direct link even
            # though the normal library hides them until the visitor opts in.
            context = browser.new_context()
            context.route('**/data/papers.json', lambda route: route.fulfill(
                json=[{**papers[0], 'historical_only': True}]))
            page = context.new_page()
            page.goto(base + '/?' + urlsplit(public_record_url(papers[0])).query)
            page.get_by_text('Shared ALEX record', exact=True).wait_for()
            assert page.locator('#results h3').inner_text() == papers[0]['title']
            assert page.locator('#results details').get_attribute('open') is not None
            context.close()
            browser.close()
    finally:
        server.shutdown()
    print('Record browser checks passed: fresh desktop/mobile contexts, DOI/source records, copy, fallback, flag URLs, clear, missing records.')


if __name__ == '__main__':
    main()

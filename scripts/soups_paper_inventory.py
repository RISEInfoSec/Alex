"""Bounded official-source SOUPS paper discovery into a NEW local directory.

This does not update the review manifest, allocate numbers, decide, or publish.
Annual-program paper labels are discovery hints and require later verification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import time
import urllib.error
import urllib.request
import urllib.robotparser
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from alex.pipelines.soups_review import legacy_records, usenix_records

HOSTS = {'cups.cs.cmu.edu', 'www.usenix.org'}
AGENT = 'ALEX-ContentReview/1.0 (+https://github.com/RISEInfoSec/Alex)'
LIMIT = 3 * 1024 * 1024


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def validated_sources(manifest, expected_blob):
    raw = Path(manifest).read_bytes()
    blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    if blob != expected_blob:
        raise ValueError('Manifest Git blob identity differs')
    data = json.loads(raw)
    coverage = data.get('annual_coverage')
    if not isinstance(coverage, list) or not 1 <= len(coverage) <= 30:
        raise ValueError('Annual source list unavailable')
    sources, years = [], set()
    for row in coverage:
        year, url = row.get('year'), row.get('source_url')
        if type(year) is not int or not 2005 <= year <= 2100 or year in years or not isinstance(url, str):
            raise ValueError('Ambiguous annual source')
        u = urlsplit(url)
        if u.scheme != 'https' or u.hostname not in HOSTS or u.port not in (None, 443) or u.username or u.password or u.fragment:
            raise ValueError('Annual source is outside the official host allowlist')
        if (year < 2014 and u.hostname != 'cups.cs.cmu.edu') or (year >= 2014 and u.hostname != 'www.usenix.org'):
            raise ValueError('Annual source host does not match period')
        years.add(year); sources.append((year, url))
    return sorted(sources)


def fetch(opener, url):
    request = urllib.request.Request(url, headers={'User-Agent': AGENT, 'Accept': 'text/html,text/plain'})
    try:
        with opener.open(request, timeout=20) as response:
            status = response.status
            content_type = response.headers.get('Content-Type', '')
            raw = response.read(LIMIT + 1)
    except urllib.error.HTTPError as exc:
        return exc.code, '', b''
    if len(raw) > LIMIT:
        raise ValueError('Source exceeds size limit')
    return status, content_type, raw


def decode_program(raw, content_type, year):
    """Decode conservatively and identify the assumption in discovery evidence."""
    match = re.search(r'charset\s*=\s*[\"\']?([\w.-]+)', content_type, re.I)
    if match:
        encoding = match.group(1)
        return raw.decode(encoding), f'http:{encoding}'
    try:
        return raw.decode('utf-8'), 'utf-8'
    except UnicodeDecodeError:
        # The 2007 CMU program is unlabeled legacy HTML, observed with Latin
        # accented author names. Preserve this assumption for later review.
        if year != 2007 or re.search(rb'charset\s*=', raw[:4096], re.I):
            raise
        return raw.decode('windows-1252'), 'windows-1252-assumed'


def run(manifest, expected_blob, destination, *, get=fetch, now=time.monotonic, sleep=time.sleep):
    sources = validated_sources(manifest, expected_blob)
    output = Path(destination)
    output.mkdir(parents=True, exist_ok=False)
    opener = urllib.request.build_opener(NoRedirect())
    history, observations, papers, seen, policies = [], [], [], set(), {}
    last_send = None
    def request(url):
        nonlocal last_send
        if last_send is not None:
            sleep(max(0, 2 - (now() - last_send)))
        last_send = now()
        entry = {'url': url, 'status': None}
        history.append(entry)
        try:
            status, content_type, body = get(opener, url)
        except (OSError, UnicodeError, ValueError, KeyError, TypeError) as exc:
            # Preserve a safe diagnostic without recording request headers or
            # exception strings that might contain sensitive URL material.
            entry['error_type'] = type(exc).__name__
            reason = getattr(exc, 'reason', None)
            if isinstance(reason, BaseException):
                entry['error_reason_type'] = type(reason).__name__
            raise
        entry['status'] = status
        return status, content_type, body
    def receipt(status, reason=None):
        result = {'status': status, 'reason': reason, 'source_manifest_blob': expected_blob,
                  'observed_at': datetime.now(timezone.utc).isoformat(), 'requests': history,
                  'annual_observations': observations, 'paper_candidates': len(papers),
                  'candidate_processing': False, 'publication_approved': False,
                  'format_verification': 'not_performed', 'doi_required': False}
        (output / 'receipt.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        (output / 'paper-candidates.json').write_text(json.dumps(papers, ensure_ascii=False, indent=2) + '\n')
        return result
    try:
        for year, url in sources:
            host = urlsplit(url).hostname
            if host not in policies:
                robots = 'https://' + host + '/robots.txt'
                status, _, body = request(robots)
                if status == 404:
                    policy = urllib.robotparser.RobotFileParser(); policy.parse([])
                elif status == 200 and len(body) <= LIMIT:
                    policy = urllib.robotparser.RobotFileParser(); policy.parse(body.decode('utf-8').splitlines())
                else:
                    return receipt('blocked', 'robots_unavailable_or_denied')
                policies[host] = policy
            if not policies[host].can_fetch(AGENT, url):
                return receipt('blocked', 'robots_disallows_source')
            status, content_type, raw = request(url)
            if status != 200 or 'html' not in content_type.lower():
                return receipt('blocked', 'source_response_unavailable')
            (output / f'year-{year}.html').write_bytes(raw)
            html, encoding = decode_program(raw, content_type, year)
            rows = (legacy_records if year < 2014 else usenix_records)(html, year, url)
            selected = [row for row in rows if row.get('document_type') == 'research_paper']
            for row in selected:
                if row['candidate_id'] in seen:
                    return receipt('blocked', 'duplicate_candidate_identity')
                seen.add(row['candidate_id']); papers.append(row)
            observations.append({'year': year, 'source_url': url, 'source_sha256': hashlib.sha256(raw).hexdigest(),
                                 'source_bytes': len(raw), 'paper_candidates': len(selected),
                                 'source_encoding': encoding,
                                 'nonpaper_program_items': len(rows) - len(selected),
                                 'coverage': 'unverified' if selected else 'gap_or_no_papers_parsed'})
            receipt('in_progress')
        return receipt('discovery_complete_pending_coverage_and_format_verification')
    except (OSError, UnicodeError, ValueError, LookupError, TypeError):
        return receipt('blocked', 'source_read_or_parse_failed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--expected-git-blob', required=True)
    parser.add_argument('--output-new-directory', required=True)
    args = parser.parse_args()
    result = run(args.manifest, args.expected_git_blob, args.output_new_directory)
    print(json.dumps({'status': result['status'], 'reason': result['reason'],
                      'paper_candidates': result['paper_candidates'], 'requests': len(result['requests'])}))
    return 0 if result['status'].startswith('discovery_complete') else 1


if __name__ == '__main__':
    raise SystemExit(main())

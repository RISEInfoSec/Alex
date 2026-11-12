import hashlib
import json

import pytest

from scripts.soups_paper_inventory import run, validated_sources


def source(tmp_path):
    manifest = tmp_path / 'manifest.json'
    manifest.write_text(json.dumps({'annual_coverage': [{'year': 2025,
        'source_url': 'https://www.usenix.org/conference/soups2025/accepted-papers'}]}))
    raw = manifest.read_bytes()
    return manifest, hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()


def test_paper_inventory_keeps_paper_without_doi_and_excludes_poster(tmp_path):
    manifest, blob = source(tmp_path)
    html = b'''<div class="node-session"><h2>Research papers</h2>
      <div class="node-paper"><h2><a href="/paper-a">Paper A</a></h2>
      <div class="field-name-field-paper-people-text">Alice</div>
      <div class="field-name-field-paper-description-long">An abstract.</div></div></div>
      <div class="node-session"><h2>Poster session</h2><div class="node-paper">
      <h2><a href="/poster-b">Poster B</a></h2>
      <div class="field-name-field-paper-people-text">Bob</div></div></div>'''
    calls = []
    def get(opener, url):
        calls.append(url)
        return (200, 'text/plain', b'User-agent: *\nAllow: /\n') if url.endswith('/robots.txt') else (200, 'text/html', html)
    out = tmp_path / 'output'
    result = run(manifest, blob, out, get=get, sleep=lambda _: None)
    papers = json.loads((out / 'paper-candidates.json').read_text())
    assert result['status'] == 'discovery_complete_pending_coverage_and_format_verification'
    assert result['doi_required'] is False and len(papers) == 1 and papers[0]['doi'] == ''
    assert papers[0]['title'] == 'Paper A' and result['annual_observations'][0]['nonpaper_program_items'] == 1
    assert result['candidate_processing'] is False and result['publication_approved'] is False
    assert len(calls) == len(result['requests']) == 2
    with pytest.raises(FileExistsError): run(manifest, blob, out, get=get, sleep=lambda _: None)


def test_denials_stop_and_preserve_actual_request_receipt(tmp_path):
    manifest, blob = source(tmp_path)
    def get(opener, url):
        if url.endswith('/robots.txt'): return 200, 'text/plain', b'User-agent: *\nAllow: /\n'
        return 429, '', b''
    output = tmp_path / 'output'
    result = run(manifest, blob, output, get=get, sleep=lambda _: None)
    assert result['status'] == 'blocked' and result['reason'] == 'source_response_unavailable'
    assert len(result['requests']) == 2 and result['requests'][-1]['status'] == 429
    assert json.loads((output / 'paper-candidates.json').read_text()) == []


def test_unverified_manifest_and_unapproved_hosts_fail_before_requests(tmp_path):
    manifest, blob = source(tmp_path)
    with pytest.raises(ValueError, match='identity'):
        validated_sources(manifest, '0' * 40)
    manifest.write_text(json.dumps({'annual_coverage': [{'year': 2025, 'source_url': 'https://example.com/program'}]}))
    raw = manifest.read_bytes()
    blob = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()
    with pytest.raises(ValueError, match='allowlist'):
        validated_sources(manifest, blob)

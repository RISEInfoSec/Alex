import assert from 'node:assert/strict';
import test from 'node:test';
import corrections from '../data/apwg-verified-corrections.json' with {type: 'json'};
import {digest} from '../checks.mjs';
import {adaptSavedCapture} from '../source-adapters.mjs';

const archive = 'https://ecrimeresearch.org/2025-accepted-research-papers';
const fixture = async body => {
  const response = {status: 200, body};
  return adaptSavedCapture({
    source: 'APWG', collection: 'apwg-fixture', archiveYear: 2025,
    request: {provider: 'ecrimeresearch.org', operation: 'GET-raw', input: {url: archive}},
    response, response_sha256: await digest(response),
  });
};
const escape = value => value.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');

test('verified APWG corrections retain each exact archive title even when markup divides a word', async () => {
  for (const entry of corrections.entries) {
    const host = entry.url_suffix.startsWith('/document/') ? 'ieeexplore.ieee.org' : 'docs.apwg.org';
    for (const title of entry.archive_titles || [entry.archive_title]) {
      const [first, ...rest] = [...title];
      const body = `<h4><a href="https://${host}${escape(entry.url_suffix)}">${escape(first)}<em>${escape(rest.join(''))}</em></a></h4>`;
      const [row] = await fixture(body);
      assert.equal(row.original_apwg_title, title);
      assert.equal(row.title, entry.title);
      assert.equal(row.authors, entry.authors);
      assert.equal(row.doi, entry.doi.toLowerCase());
      assert.equal(row.year, String(entry.year));
      assert.equal(row.apwg_year, 2025);
      assert.equal(row.bibliographic_correction_source, entry.evidence_url);
      assert.equal(row.venue_evidence_url, entry.venue_evidence_url || '');
    }
  }
});

test('APWG keeps an adjacent byline and skips a link on an unapproved port', async () => {
  const body = '<h4><a href="https://ieeexplore.ieee.org:8443/document/1/">Example paper on a wrong port</a></h4>'
    + '<p>Unrelated Name</p>'
    + '<h4><a href="https://ieeexplore.ieee.org/document/2/">Example papers with <i>inline</i> formatting</a></h4>'
    + '<p><strong>Sample Author</strong> ; Second Author</p>';
  const rows = await fixture(body);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].authors, 'Sample Author; Second Author');
  assert.equal(rows[0].author_source, 'APWG archive byline');
  assert.equal(rows[0].year, '');
  assert.equal(rows[0].venue, '');
});

(function (root) {
  'use strict';
  const PUBLIC_BASE = 'https://alex.riseinfosec.org/';
  const text = value => String(value ?? '').trim();
  function doi(value) {
    return text(value).replace(/^https?:\/\/(?:dx\.)?doi\.org\//i, '').replace(/^doi:\s*/i, '').toLowerCase();
  }
  function source(value) {
    try {
      const url = new URL(text(value));
      if (!['https:', 'http:'].includes(url.protocol) || url.username || url.password) return '';
      url.hash = '';
      return url.href;
    } catch { return ''; }
  }
  function keys(paper) {
    const values = [];
    const d = doi(paper.doi);
    if (d) values.push('doi:' + d);
    for (const value of [paper.source_url, paper.link]) {
      const url = source(value);
      if (url) values.push('url:' + url);
    }
    // The fallback includes year and author, never a title-only or row-number match.
    if (text(paper.title)) values.push('bib:' + JSON.stringify([
      text(paper.title).replace(/\s+/g, ' ').toLowerCase(),
      text(paper.year).replace(/\.0$/, ''),
      text(paper.author).replace(/\s+/g, ' ').toLowerCase()
    ]));
    return [...new Set(values)];
  }
  function publicUrl(paper) {
    const key = keys(paper)[0];
    if (!key) return '';
    const url = new URL(PUBLIC_BASE);
    url.searchParams.set('record', key);
    return url.href;
  }
  function resolve(papers, key) {
    const primary = papers.filter(paper => keys(paper)[0] === key);
    if (primary.length) return primary.length === 1 ? primary[0] : null;
    const matches = papers.filter(paper => keys(paper).includes(key));
    return matches.length === 1 ? matches[0] : null;
  }
  function attach(container, paper) {
    const doc = container.ownerDocument;
    const actions = doc.createElement('div');
    actions.className = 'record-actions';
    const direct = doc.createElement('a');
    direct.href = publicUrl(paper);
    direct.textContent = 'Open record';
    const copy = doc.createElement('button');
    copy.type = 'button';
    copy.className = 'secondary';
    copy.textContent = 'Copy link';
    const status = doc.createElement('span');
    status.setAttribute('role', 'status');
    const fallback = doc.createElement('input');
    fallback.type = 'url';
    fallback.readOnly = true;
    fallback.hidden = true;
    fallback.setAttribute('aria-label', 'Public record link');
    copy.addEventListener('click', async () => {
      try {
        await root.navigator.clipboard.writeText(publicUrl(paper));
        status.textContent = 'Link copied.';
        fallback.hidden = true;
      } catch {
        fallback.value = publicUrl(paper);
        fallback.hidden = false;
        fallback.focus();
        fallback.select();
        status.textContent = 'Copy the selected link.';
      }
    });
    actions.append(direct, copy, status, fallback);
    const details = container.querySelector('details');
    container.insertBefore(actions, details);
  }
  const api = {keys, publicUrl, resolve, attach};
  if (typeof module !== 'undefined' && module.exports) module.exports = api;
  else root.AlexRecords = api;
})(typeof window !== 'undefined' ? window : globalThis);

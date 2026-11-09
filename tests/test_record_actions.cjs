const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const code = fs.readFileSync(path.join(__dirname, '../assets/record-actions.js'), 'utf8');
const sandbox = {module: {exports: {}}, URL};
vm.runInNewContext(code, sandbox);
const api = sandbox.module.exports;
const corpus = JSON.parse(fs.readFileSync(path.join(__dirname, '../data/papers.json'), 'utf8'));
const urls = corpus.map(p => api.publicUrl(p));
assert.equal(new Set(urls).size, corpus.length, 'Every public record must have a unique link');
const reversed = corpus.slice().reverse().map((p, i) => ({...p, id: i + 50000}));
const identities = new Map();
for (const paper of corpus) for (const key of api.keys(paper)) {
  if (!identities.has(key)) identities.set(key, []);
  identities.get(key).push(paper);
}
for (const [i, paper] of corpus.entries()) {
  const url = new URL(urls[i]);
  assert.equal(url.origin, 'https://alex.riseinfosec.org');
  assert.equal(url.pathname, '/');
  assert.deepEqual([...url.searchParams.keys()], ['record']);
  assert.equal(identities.get(url.searchParams.get('record')).filter(p => api.keys(p)[0] === url.searchParams.get('record')).length, 1, 'Shared identity must resolve uniquely');
  if (i % 1000 === 0) assert.equal(api.resolve(reversed, url.searchParams.get('record')).title, paper.title);
}
assert.equal(api.flagUrl, undefined, 'Public record actions must not expose a deletion link');
const example = {title: 'Example', year: 2026, author: 'A', source_url: 'https://example.org/paper#part'};
const oldKey = new URL(api.publicUrl(example)).searchParams.get('record');
assert.equal(api.resolve([{...example, doi: '10.1234/new'}], oldKey).title, 'Example');
assert.equal(api.publicUrl({doi: 'https://doi.org/10.1234/UPPER'}), api.publicUrl({doi: '10.1234/upper'}));
assert.equal(api.resolve([example, {...example}], oldKey), null, 'Ambiguous identity must never choose a record');
assert.equal(api.resolve(corpus, 'doi:missing'), null);
assert.notEqual(api.publicUrl({title: 'Same title', year: 2025}), api.publicUrl({title: 'Same title', year: 2026}));

function element(tag, doc) {
  return {tag, ownerDocument: doc, children: [], hidden: false, listeners: {},
    append(...children) {this.children.push(...children);},
    insertBefore(child) {this.children.push(child);},
    querySelector() {return null;},
    setAttribute(name, value) {this[name] = value;},
    addEventListener(name, listener) {this.listeners[name] = listener;},
    focus() {this.focused = true;},
    select() {this.selected = true;}
  };
}
(async () => {
  const doc = {createElement(tag) {return element(tag, doc);}};
  const container = element('div', doc);
  sandbox.navigator = {clipboard: {async writeText(value) {sandbox.copied = value;}}};
  api.attach(container, example);
  const [actions] = container.children;
  assert.equal(container.children.length, 1, 'No public removal-request disclaimer or form');
  const [direct, copy, status, fallback] = actions.children;
  assert.equal(actions.children.length, 4);
  assert.ok(!actions.children.some(child => child.textContent === 'Flag for deletion'));
  await copy.listeners.click();
  assert.equal(sandbox.copied, api.publicUrl(example));
  assert.equal(status.textContent, 'Link copied.');
  assert.equal(direct.href, api.publicUrl(example));
  sandbox.navigator.clipboard.writeText = async () => {throw Error('denied');};
  await copy.listeners.click();
  assert.equal(fallback.hidden, false);
  assert.equal(fallback.value, api.publicUrl(example));
  assert.ok(fallback.focused && fallback.selected);
  assert.equal(status.textContent, 'Copy the selected link.');
  console.log('Record sharing tests passed for ' + corpus.length + ' records, clipboard success and fallback; no public deletion control.');
})().catch(error => {console.error(error); process.exitCode = 1;});

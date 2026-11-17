import {parse} from 'parse5';
import {SaxesParser} from 'saxes';
import {decodeHTML} from 'entities';
import {POLICY, canonicalDoi, clean, digest, evaluate, excluded, identities, normalizeTitle} from './checks.mjs';
import {normalizeCrossref} from './core.mjs';

const MAX_CAPTURE_BYTES = 512 * 1024;
const MAX_ITEMS = 50;
const ATOM = 'http://www.w3.org/2005/Atom';
const list = value => value == null ? [] : requiredList(value);
const strip = value => clean(decodeHTML(clean(value)).replace(/<[^>]+>/g, ' '));
const authorNames = (authors, key = 'name') => list(authors).map(author => clean(author?.[key])).filter(Boolean).join('; ');
const validDate = value => /^\d{4}-\d{2}-\d{2}$/.test(value) && Number.isFinite(Date.parse(value))
  && new Date(value).toISOString().slice(0, 10) === value;

function requiredList(value) {
  if (!Array.isArray(value)) throw Error('invalid_source_list');
  return value;
}

function openAlex(item) {
  const authors = list(item.authorships);
  const indexed = Object.entries(item.abstract_inverted_index ?? {}).flatMap(([word, offsets]) =>
    list(offsets).map(offset => {
      if (!Number.isSafeInteger(offset) || offset < 0) throw Error('invalid_abstract_offset');
      return [offset, word];
    }));
  const location = item.primary_location;
  return {
    title: item.title ?? '', authors: authorNames(authors.map(a => a.author), 'display_name'),
    affiliations: [...new Set(authors.flatMap(a => list(a.institutions).map(i => clean(i.display_name))).filter(Boolean))].join('; '),
    year: item.publication_year ?? '', doi: clean(item.ids?.doi).replace(/^https:\/\/doi\.org\//, ''),
    abstract: indexed.sort((a, b) => a[0] - b[0]).map(entry => entry[1]).join(' '),
    venue: location?.source?.display_name ?? '', source_url: location?.landing_page_url ?? '',
    citation_count: item.cited_by_count ?? '', discovery_resource_type: item.type ?? '',
  };
}

const jsonSources = {
  Crossref: ['api.crossref.org', '/works', data => data?.message?.items, normalizeCrossref],
  OpenAlex: ['api.openalex.org', '/works', data => data?.results, openAlex],
  Zenodo: ['zenodo.org', '/api/records', data => data?.hits?.hits, item => {
    const m = item.metadata ?? {};
    const date = clean(m.publication_date);
    return {
      title: m.title ?? '', authors: authorNames(m.creators), year: validDate(date) || /^\d{4}$/.test(date) ? date.slice(0, 4) : '',
      doi: m.doi ?? '', abstract: strip(m.description), venue: m.journal?.title ?? '',
      source_url: item.links?.html ?? '', citation_count: '', discovery_resource_type: m.resource_type?.type ?? '',
      discovery_resource_subtype: m.resource_type?.subtype ?? '',
    };
  }],
  'Semantic Scholar': ['api.semanticscholar.org', '/graph/v1/paper/search', data => data?.data, item => ({
    title: item.title ?? '', authors: authorNames(item.authors), year: item.year ?? '', doi: item.externalIds?.DOI ?? '',
    abstract: item.abstract ?? '', venue: item.venue ?? '', source_url: item.url ?? '', citation_count: item.citationCount ?? '',
  })],
  CORE: ['api.core.ac.uk', '/v3/search/works', data => data?.results, item => ({
    title: item.title ?? '', authors: authorNames(item.authors), year: item.yearPublished ?? '', doi: item.doi ?? '',
    abstract: item.abstract ?? '', venue: item.publisher ?? '', source_url: item.downloadUrl ?? '', citation_count: '',
  })],
  GitHub: ['api.github.com', '/search/repositories', data => data?.items, item => ({
    title: item.full_name ?? '', authors: item.owner?.login ?? '', year: '', doi: '', abstract: item.description ?? '',
    venue: '', source_url: item.html_url ?? '', citation_count: '', discovery_resource_type: 'software',
  })],
};

function atomRecords(body) {
  const parser = new SaxesParser({xmlns: true});
  const stack = [];
  const entries = [];
  parser.on('doctype', () => { throw Error('arxiv_doctype_refused'); });
  parser.on('opentag', tag => {
    if (stack.length >= 16 || (!stack.length && (tag.uri !== ATOM || tag.local !== 'feed'))) {
      throw Error('invalid_arxiv_feed');
    }
    stack.push({uri: tag.uri, name: tag.local, text: '', children: []});
  });
  const append = value => { if (stack.length) stack.at(-1).text += value; };
  parser.on('text', append);
  parser.on('cdata', append);
  parser.on('closetag', () => {
    const node = stack.pop();
    if (stack.length === 1 && node.uri === ATOM && node.name === 'entry') {
      if (entries.length === MAX_ITEMS) throw Error('source_item_limit');
      entries.push(node);
    } else if (stack.length > 1) {
      stack.at(-1).children.push(node);
    }
  });
  parser.write(body).close();
  const all = (node, name) => node.children.filter(child => child.uri === ATOM && child.name === name);
  const field = (node, name) => clean(all(node, name)[0]?.text);
  return entries.map(entry => {
    const arxivId = field(entry, 'id').match(/^https?:\/\/(?:export\.)?arxiv\.org\/abs\/([a-z.-]+\/\d{7}|\d{4}\.\d{4,5})(?:v\d+)?$/i)?.[1];
    const title = field(entry, 'title');
    const abstract = strip(field(entry, 'summary'));
    if (!arxivId || !title || !abstract) throw Error('invalid_arxiv_entry');
    const date = field(entry, 'published').slice(0, 10);
    const sourceUrl = 'https://arxiv.org/abs/' + arxivId;
    return {
      arxiv_id: arxivId, title, abstract, authors: all(entry, 'author').map(a => field(a, 'name')).filter(Boolean).join('; '),
      year: validDate(date) ? date.slice(0, 4) : '', source_url: sourceUrl, venue: '', doi: '', citation_count: '',
      discovery_resource_type: 'preprint',
      ...(validDate(date) ? {publication_date: date, publication_date_source: sourceUrl, publication_date_status: 'verified',
        publication_date_basis: 'arXiv first public preprint date; not a revision date'} : {}),
    };
  });
}

function* elements(root) {
  const stack = [root];
  while (stack.length) {
    const node = stack.pop();
    yield node;
    for (let i = (node.childNodes?.length ?? 0) - 1; i >= 0; i--) stack.push(node.childNodes[i]);
  }
}

const attr = (node, name) => node.attrs?.find(a => a.name === name)?.value;
const text = node => clean([...elements(node)].filter(n => n.nodeName === '#text').map(n => n.value).join(' '));

function apwgRecords(body, url, archiveYear) {
  if (!Number.isSafeInteger(archiveYear) || archiveYear < 2007 || archiveYear > POLICY.year) throw Error('invalid_apwg_archive_year');
  const candidates = new Map();
  for (const link of elements(parse(body))) {
    if (link.tagName !== 'a' || !attr(link, 'href')) continue;
    const target = new URL(attr(link, 'href'), url);
    const title = text(link);
    if (title.length < 20 || title.split(' ').length < 4 || !['http:', 'https:'].includes(target.protocol) || target.username || target.password) continue;
    const host = target.hostname.toLowerCase();
    const path = target.pathname.toLowerCase();
    const ieee = /^(www\.)?ieeexplore\.ieee\.org$/.test(host) && /\/(document|abstract)\//.test(path);
    const pdf = path.endsWith('.pdf') && /\.(amazonaws\.com|apwg\.org|ecrimeresearch\.org)$/.test(host);
    const key = normalizeTitle(title);
    if (!(ieee || pdf) || !key || candidates.has(key)) continue;
    candidates.set(key, {title, authors: '', year: '', doi: '', venue: '', abstract: '', publisher: '', author_source: '',
      publication_year_source: '', venue_source: '', venue_evidence_url: '',
      source_url: target.href, apwg_source_url: target.href, collection_url: url.href,
      collection_source: 'APWG.org eCrimes Research', apwg_year: archiveYear});
  }
  if (!candidates.size) throw Error('apwg_no_paper_links');
  return [...candidates.values()];
}

const collections = {
  FIRST: ['first.org', 'FIRST'],
  Bellingcat: ['bellingcat.com', 'Bellingcat'],
  M3AAWG: ['m3aawg.org', 'M3AAWG'],
  SANS: ['sans.org', 'SANS'],
  SOUPS: ['usenix.org', 'SOUPS (Symposium On Usable Privacy and Security) and USENIX (the Advanced Computing Systems Association)'],
  'Virus Bulletin': ['virusbulletin.com', 'Virus Bulletin'],
};

function namedRecord(body, url, source) {
  const [host, label] = collections[source];
  if (![host, 'www.' + host].includes(url.hostname) || url.pathname === '/') throw Error('collection_item_url_required');
  if (source === 'SOUPS' && !/^\/conference\/soups\d+\/presentation\//i.test(url.pathname)) throw Error('soups_item_url_required');
  const head = parse(body).childNodes.find(n => n.tagName === 'html')?.childNodes.find(n => n.tagName === 'head');
  const meta = new Map();
  for (const el of head?.childNodes ?? []) {
    if (el.tagName !== 'meta') continue;
    const key = clean(attr(el, 'name')).toLowerCase();
    if (!key.startsWith('citation_')) continue;
    const value = clean(attr(el, 'content'));
    if (value) meta.set(key, [...(meta.get(key) ?? []), value]);
  }
  const one = name => {
    const values = [...new Set(meta.get('citation_' + name) ?? [])];
    if (values.length > 1) throw Error('conflicting_collection_metadata');
    return values[0] ?? '';
  };
  const title = one('title');
  if (!title) throw Error('collection_bibliographic_metadata_missing');
  const date = one('publication_date') || one('date');
  const normalized = date.replaceAll('/', '-');
  const year = (validDate(normalized) || /^\d{4}$/.test(normalized)) ? normalized.slice(0, 4) : '';
  // A citation title on a collection page does not by itself prove paper type.
  return {title, authors: (meta.get('citation_author') ?? []).join('; '), year, doi: one('doi'),
    abstract: one('abstract'), venue: one('journal_title') || one('conference_title'), source_url: url.href,
    collection_source: label, discovery_resource_type: one('article_type'), collection_type_needs_verification: true};
}

export async function adaptSavedCapture({source, collection, request, response, response_sha256, archiveYear}) {
  if (!clean(collection) || !request || !response || !Object.hasOwn(response, 'body')) throw Error('invalid_capture');
  const url = new URL(request.input?.url);
  if (!['http:', 'https:'].includes(url.protocol) || url.username || url.password || url.search || url.hash
      || url.port || request.provider !== url.hostname || !['GET-json', 'GET-raw'].includes(request.operation)) {
    throw Error('invalid_capture_request');
  }
  if (new TextEncoder().encode(JSON.stringify(response)).length > MAX_CAPTURE_BYTES) throw Error('source_capture_size_limit');
  if (await digest(response) !== response_sha256) throw Error('capture_hash_mismatch');
  if (response.status !== 200) throw Error('source_response_not_successful');
  let records;
  if (Object.hasOwn(jsonSources, source)) {
    const [host, path, select, normalize] = jsonSources[source];
    const doi = source === 'Crossref' && url.pathname.startsWith('/works/') ? canonicalDoi(decodeURIComponent(url.pathname.slice(7))) : '';
    if (url.protocol !== 'https:' || url.hostname !== host || (url.pathname !== path && !doi) || request.operation !== 'GET-json') {
      throw Error('source_request_mismatch');
    }
    const singleton = response.body?.message;
    if (doi && (!/^10\.\d{4,9}\/\S+$/.test(doi) || canonicalDoi(singleton?.DOI) !== doi)) {
      throw Error('source_response_identity_mismatch');
    }
    const items = doi ? [singleton] : requiredList(select(response.body));
    if (items.length > MAX_ITEMS) throw Error('source_item_limit');
    if (items.some(i => !i || typeof i !== 'object' || Array.isArray(i))) throw Error('invalid_source_item');
    records = items.map(item => normalize(item, collection));
  } else {
    if (request.operation !== 'GET-raw' || typeof response.body !== 'string' || !response.body.trim()) throw Error('invalid_source_text');
    if (source === 'arXiv' && url.hostname === 'export.arxiv.org' && url.pathname === '/api/query') records = atomRecords(response.body);
    else if (url.protocol === 'https:' && source === 'APWG' && /^(www\.)?ecrimeresearch\.org$/.test(url.hostname)) {
      records = apwgRecords(response.body, url, archiveYear);
    } else if (url.protocol === 'https:' && Object.hasOwn(collections, source)) {
      records = [namedRecord(response.body, url, source)];
    } else throw Error('source_request_mismatch');
  }
  if (records.length > MAX_ITEMS) throw Error('source_item_limit');
  return records.map(record => ({...record, discovery_source: source, collection}));
}

export async function checkCapturedRecord(record, document, implementationHash) {
  const content_hash = await digest(record);
  try {
    identities(record);
  } catch {
    return {record, content_hash, disposition: 'held', reason: 'title_and_year_required'};
  }
  const checks = await evaluate(record, document, implementationHash);
  const reason = excluded(record) ? 'existing_editorial_exclusion'
    : record.collection_type_needs_verification ? 'collection_type_needs_verification'
    : Object.values(checks).some(check => check.result !== 'pass') ? 'required_check_held' : null;
  return {record, content_hash, disposition: reason ? 'held' : 'awaiting_review', reason, checks};
}

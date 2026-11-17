import {readFileSync} from 'node:fs';
import {digest} from '../checks.mjs';

export async function captureFixtures() {
  const source = JSON.parse(readFileSync(new URL('../data/scenario.json', import.meta.url)));
  const fixtures = [{
    capture: {source: 'Crossref', collection: 'source-adapter-fixture', ...source.captures[0]},
    expected: [{year: 2024}, {}, {discovery_resource_type: 'book'}, {}, {}, {year: ''}],
  }];
  const fixture = async (name, url, body, expected, options = {}) => {
    const response = {status: 200, body};
    fixtures.push({capture: {source: name, collection: 'source-adapter-fixture',
      request: {provider: new URL(url).hostname, operation: typeof body === 'string' ? 'GET-raw' : 'GET-json',
        input: {url, params: options.params ?? {}}, contract: 'alex-stage2-recorded-v1'},
      response, response_sha256: await digest(response), ...(options.year ? {archiveYear: options.year} : {})}, expected: [expected]});
  };
  await fixture('OpenAlex', 'https://api.openalex.org/works', {results: [{
    title:'Saved dataset', publication_year:2025, type:'dataset',
    ids:{doi:'https://doi.org/10.0000/saved'},
    authorships:[{author:{display_name:'Synthetic Author'},institutions:[{display_name:'University'}]}],
    abstract_inverted_index:{Synthetic:[0],dataset:[1]},
    primary_location:{landing_page_url:'https://example.invalid/dataset',source:{display_name:'Fixture'}},
    cited_by_count:0,
  }]}, {doi:'10.0000/saved',abstract:'Synthetic dataset',discovery_resource_type:'dataset',affiliations:'University',citation_count:0});
  await fixture('Zenodo','https://zenodo.org/api/records',{hits:{hits:[{metadata:{title:'Saved book',publication_date:'2024',
    resource_type:{type:'publication',subtype:'book'},creators:[{name:'Synthetic Author'}],description:'<p>Saved abstract</p>'},
    links:{html:'https://example.invalid/book'}}]}},{year:'2024',citation_count:'',abstract:'Saved abstract',discovery_resource_subtype:'book'});
  await fixture('Semantic Scholar','https://api.semanticscholar.org/graph/v1/paper/search',
    {data:[{title:'Saved paper',year:2024,authors:[{name:'Synthetic Author'}],externalIds:{DOI:'10.0000/saved'},citationCount:0}]},
    {authors:'Synthetic Author',doi:'10.0000/saved',citation_count:0});
  await fixture('CORE','https://api.core.ac.uk/v3/search/works',
    {results:[{title:'Saved work',authors:[{name:'Synthetic Author'}],yearPublished:2023,downloadUrl:'https://example.invalid/work'}]},
    {year:2023,citation_count:'',source_url:'https://example.invalid/work'});
  await fixture('GitHub','https://api.github.com/search/repositories',
    {items:[{full_name:'synthetic/fixture',owner:{login:'synthetic'},description:'Saved code',html_url:'https://example.invalid/code',created_at:'2024-01-01'}]},
    {discovery_resource_type:'software',year:''});
  await fixture('APWG','https://ecrimeresearch.org/example/archive',
    '<html><a href="https://apwg-craftcms-assets.s3.amazonaws.com/synthetic-stage2-paper.pdf">A saved cybersecurity paper title</a></html>',
    {year:'',venue:'',apwg_year:2025,collection_source:'APWG.org eCrimes Research'},{year:2025});
  await fixture('arXiv','http://export.arxiv.org/api/query',
    '<feed xmlns="http://www.w3.org/2005/Atom"><entry><id>https://arxiv.org/abs/2601.12345</id><title>Saved cybersecurity paper</title>'
    + '<summary>Saved abstract</summary><author><name>Synthetic Author</name></author><published>2026-01-02T00:00:00Z</published></entry></feed>',
    {publication_date:'2026-01-02',year:'2026',discovery_resource_type:'preprint'});
  const namedSources = {
    FIRST:'https://www.first.org/conference/test/item',
    Bellingcat:'https://www.bellingcat.com/resources/test',
    M3AAWG:'https://www.m3aawg.org/published-documents/test',
    SANS:'https://www.sans.org/white-papers/test',
    SOUPS:'https://www.usenix.org/conference/soups2025/presentation/test',
    'Virus Bulletin':'https://www.virusbulletin.com/conference/test',
  };
  for (const [label,url] of Object.entries(namedSources)) {
    await fixture(label,url,'<!doctype html><html><head><meta name="citation_title" content="Synthetic bibliographic record">'
      + '<meta name="citation_author" content="Fixture Author"><meta name="citation_publication_date" content="2025/03/01">'
      + '<meta name="citation_article_type" content="presentation"></head><body><article>Fixture body.</article></body></html>',
      {year:'2025',authors:'Fixture Author',collection_type_needs_verification:true,discovery_resource_type:'presentation'});
  }
  return fixtures;
}

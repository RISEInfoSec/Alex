/** Bounded serial acquisition of official SOUPS pages; metadata only, no PDFs.
 * node scripts/soups_fetch.mjs [.cache/soups] [--refresh]
 * Rerun after assigning review numbers to acquire individual citations.
 */
import fs from 'node:fs/promises';
import path from 'node:path';

const args = process.argv.slice(2);
const directory = path.resolve(args.find(a => !a.startsWith('--')) || '.cache/soups');
const refresh = args.includes('--refresh');
const origins = new Set(['https://soups.page', 'https://cups.cs.cmu.edu', 'https://www.usenix.org']);
await fs.mkdir(directory, {recursive:true});
const logPath = path.join(directory, 'fetch-log.json');
let log = [];
try { log = JSON.parse(await fs.readFile(logPath, 'utf8')); } catch(e) { if(e.code !== 'ENOENT') throw e; }
let requests = 0;
async function snapshot(url, key) {
  if (!origins.has(new URL(url).origin) || /\.pdf(?:$|\?)/i.test(url)) throw new Error('Not an allowed HTML source: '+url);
  if (!/^[a-z0-9-]+$/.test(key)) throw new Error('Invalid snapshot key');
  const prior = log.findLast(r => r.key === key);
  const file = path.join(directory, key+'.html');
  if (!refresh && prior?.status === 200) return fs.readFile(file, 'utf8');
  if (++requests > 180) throw new Error('Acquisition request budget exceeded');
  await new Promise(r => setTimeout(r, 550));
  let entry, body = '';
  try {
    // Inspect each redirect before fetching it, keeping acquisition on official hosts.
    let target = url, response;
    for (let hop=0;hop<8;hop++) {
      response = await fetch(target, {redirect:'manual', signal:AbortSignal.timeout(20000)});
      if (![301,302,303,307,308].includes(response.status)) break;
      const next = new URL(response.headers.get('location'), target);
      if (!origins.has(next.origin)) throw new Error('Redirect outside official allowlist: '+next.origin);
      await new Promise(r => setTimeout(r, 550));
      target = next.href;
    }
    if (!response || response.status >= 300 && response.status < 400) throw new Error('Redirect limit exceeded');
    const contentType = response.headers.get('content-type') || '';
    if (!/text\/(html|plain)/i.test(contentType)) throw new Error('Unexpected content type: '+contentType);
    body = await response.text();
    if (Buffer.byteLength(body) > 3*1024*1024) throw new Error('HTML source exceeds 3 MiB');
    entry = {url, final_url:target, status:response.status, key, bytes:Buffer.byteLength(body), retrieved_at:new Date().toISOString()};
    await fs.writeFile(file,body);
  } catch(e) {entry={url,key,error:String(e),retrieved_at:new Date().toISOString()};}
  log = log.filter(r=>r.key!==key); log.push(entry);
  await fs.writeFile(logPath,JSON.stringify(log,null,2)+'\n');
  console.log(JSON.stringify(entry));
  return entry.status===200 ? body : '';
}
function links(html, base) {
  return [...html.matchAll(/<a\b[^>]*href\s*=\s*["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi)]
    .map(m=>({url:new URL(m[1].replaceAll('&amp;','&'),base).href,text:m[2].replace(/<[^>]+>/g,'').trim()}));
}
const index = await snapshot('https://soups.page/','index');
const allLinks = links(index,'https://soups.page/');
for (const l of allLinks.filter(l=>/^20\d\d$/.test(l.text)&&new URL(l.url).hostname==='www.usenix.org'))
  await snapshot(l.url,'year-'+l.text);
const legacyIndex = await snapshot('https://cups.cs.cmu.edu/soups/','legacy-index');
const oldLinks = links(legacyIndex,'https://cups.cs.cmu.edu/soups/');
for (let year=2005;year<=2013;year++) {
  const home = oldLinks.find(l=>l.url===`https://cups.cs.cmu.edu/soups/${year}/`);
  if (!home) continue;
  const html = await snapshot(home.url,'legacy-home-'+year);
  const program = links(html,home.url).find(l=>/^program$/i.test(l.text));
  if (program) await snapshot(program.url,'program-'+year);
}
for (const l of allLinks.filter(l=>/poster proceedings|workshops, details/i.test(l.text))) {
  const kind=/poster/i.test(l.text)?'posters':'workshops';
  const year=new URL(l.url).pathname.match(/20\d\d/)?.[0];
  if(year) await snapshot(l.url,kind+'-'+year);
}
let manifest;
try { manifest=JSON.parse(await fs.readFile('config/soups_review_manifest.json','utf8')); } catch(e) {if(e.code!=='ENOENT')throw e;}
for (const row of manifest?.records || []) {
  if (!row.review_number || new URL(row.source_url).hostname!=='www.usenix.org') continue;
  const slug=new URL(row.source_url).pathname.split('/').pop();
  await snapshot(row.source_url,`paper-${row.year}-${slug}`);
}

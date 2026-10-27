/** Serial, resumable retrieval of source-linked ancillary HTML; never imports papers. */
import fs from 'node:fs/promises';
import path from 'node:path';
import crypto from 'node:crypto';
import {fileURLToPath} from 'node:url';

export async function fetchSources(root, queuePath, limit = 20) {
  const directory = path.join(root, '.cache/soups/ancillary');
  await fs.mkdir(directory, {recursive: true});
  const logPath = path.join(directory, 'fetch-log.json');
  const log = JSON.parse(await fs.readFile(logPath, 'utf8').catch(e => {
    if (e.code === 'ENOENT') return '[]';
    throw e;
  }));
  const queue = JSON.parse(await fs.readFile(queuePath, 'utf8'));
  const done = new Set(log.map(x => x.url));
  const results = [];
  for (const source of queue) {
    const url = source.url.replace(/^http:/, 'https:').split('#')[0];
    if (done.has(url)) continue;
    if (results.length >= Math.min(limit, 20)) break;
    const parsed = new URL(url);
    if (parsed.protocol !== 'https:' || parsed.username || parsed.password ||
        !source.source_url || /\.(pdf|zip|pptx?)$/i.test(parsed.pathname)) throw new Error('Not source-linked HTML: ' + url);
    const entry = {...source, url, retrieved_at: new Date().toISOString()};
    entry.snapshot = crypto.createHash('sha256').update(url).digest('hex').slice(0, 20) + '.html';
    try {
      let target = url, response;
      for (let hop = 0; hop < 6; hop++) {
        response = await fetch(target, {redirect: 'manual', signal: AbortSignal.timeout(8000)});
        if (![301, 302, 303, 307, 308].includes(response.status)) break;
        const next = new URL(response.headers.get('location'), target);
        if (next.origin !== parsed.origin) throw new Error('External redirect needs source verification: ' + next.href);
        target = next.href;
        await new Promise(r => setTimeout(r, 550));
      }
      entry.status = response.status;
      entry.final_url = target;
      if (!/text\/html/i.test(response.headers.get('content-type') || '')) throw new Error('Not HTML');
      const body = await response.text();
      if (Buffer.byteLength(body) > 3 * 1024 * 1024) throw new Error('HTML exceeds 3 MiB');
      await fs.writeFile(path.join(directory, entry.snapshot), body);
    } catch (error) { entry.error = String(error); }
    log.push(entry); done.add(url); results.push(entry);
    await fs.writeFile(logPath, JSON.stringify(log, null, 2) + '\n');
    await new Promise(r => setTimeout(r, 550));
  }
  return {fetched: results.length, remaining: queue.filter(x => !done.has(x.url.replace(/^http:/, 'https:').split('#')[0])).length,
    results: results.map(({url, status, error}) => ({url, status, error}))};
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const root = process.cwd();
  const queue = path.resolve(process.argv[2] || 'config/soups_ancillary_sources.json');
  console.log(JSON.stringify(await fetchSources(root, queue, 20), null, 2));
}

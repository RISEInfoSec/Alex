import {canonical, canonicalDoi, digest, hash, hashBytes} from './checks.mjs';
import {adaptSavedCapture, checkCapturedRecord} from './source-adapters.mjs';

export const PILOT_DOI = '10.1145/1280680.1280692';
const PROVIDER = 'Crossref';
const PILOT_URL = 'https://api.crossref.org/works/' + PILOT_DOI;
const NAMESPACE = 'alex-stage4-20261117';
const MAX_RESPONSE_BYTES = 96 * 1024;
const RESPONSE_HEADERS = ['content-type', 'retry-after', 'x-rate-limit-limit', 'x-rate-limit-interval'];
const toHex = bytes => Array.from(bytes, byte => byte.toString(16).padStart(2, '0')).join('');
const fromHex = value => {
  if (value.length > MAX_RESPONSE_BYTES * 2 || value.length % 2 || /[^0-9a-f]/.test(value)) throw Error('invalid_provider_response_bytes');
  return Uint8Array.from(value.match(/../g) ?? [], pair => Number.parseInt(pair, 16));
};

export async function retainCapture(db, capture, implementationHash) {
  const {source, collection, request, archiveYear, response_sha256} = capture;
  if (typeof source !== 'string' || !source || source.length > 64 || typeof collection !== 'string'
      || !collection || collection.length > 128 || request?.contract !== 'alex-stage2-recorded-v1'
      || typeof response_sha256 !== 'string' || await digest(capture.response) !== response_sha256) {
    throw Error('invalid_capture_identity');
  }
  const input = canonical(capture);
  const captureHash = await hash(input);
  const id = await digest({namespace: NAMESPACE, implementationHash, source, collection, request, archiveYear});
  const prior = await db.prepare('SELECT capture_hash, status, reason FROM adapter_captures WHERE id=?').bind(id).first();
  if (prior) {
    if (prior.capture_hash !== captureHash) throw Error('capture_conflict');
    return {id, status: prior.status, reason: prior.reason, replay: true};
  }
  let records = [];
  let reason = null;
  try {
    records = await adaptSavedCapture(capture);
  } catch (error) {
    reason = /^[a-z_]+$/.test(error.message) ? error.message : 'invalid_retained_source';
  }
  const results = [];
  for (const record of records) {
    const identity = await digest(record);
    results.push(await checkCapturedRecord(record, capture.documents?.[identity], implementationHash));
  }
  const status = reason || results.some(result => result.disposition === 'held') ? 'held' : 'bounded_capture_processed';
  const guard = db.prepare(`SELECT json(CASE WHEN NOT EXISTS (SELECT 1 FROM adapter_captures WHERE id=? AND capture_hash<>?)
    THEN 'true' ELSE 'capture_conflict' END)`).bind(id, captureHash);
  await db.batch([
    guard,
    db.prepare(`INSERT OR IGNORE INTO adapter_captures (id,source,capture_hash,capture,status,reason) VALUES(?,?,?,?,?,?)`)
      .bind(id, source, captureHash, input, status, reason),
    ...await Promise.all(results.map(async (result, position) => {
      const value = canonical(result);
      return db.prepare('INSERT OR IGNORE INTO adapter_results VALUES(?,?,?,?)')
        .bind(id, position, value, await hash(value));
    })),
  ]);
  return {id, status, reason, records: results.length, held: results.filter(result => result.disposition === 'held').length};
}

export async function readCapture(db, id) {
  const capture = await db.prepare('SELECT capture_hash,status,reason FROM adapter_captures WHERE id=?').bind(id).first();
  if (!capture) return null;
  const {results} = await db.prepare('SELECT result,result_hash FROM adapter_results WHERE capture_id=? ORDER BY position')
    .bind(id).all();
  const records = [];
  for (const row of results) {
    if (await hash(row.result) !== row.result_hash) throw Error('capture_result_hash_mismatch');
    records.push(JSON.parse(row.result));
  }
  return {...capture, id, records};
}

async function boundedBody(response) {
  const parts = [];
  let length = 0;
  const reader = response.body?.getReader();
  if (!reader) return new Uint8Array();
  for (;;) {
    const {done, value} = await reader.read();
    if (done) break;
    length += value.length;
    if (length > MAX_RESPONSE_BYTES) {
      await reader.cancel();
      throw Error('provider_response_size_limit');
    }
    parts.push(value);
  }
  const bytes = new Uint8Array(length);
  let position = 0;
  for (const part of parts) {
    bytes.set(part, position);
    position += part.length;
  }
  return bytes;
}

async function fetchCrossref(send) {
  let response;
  let headers;
  try {
    response = await send(PILOT_URL, {
      method: 'GET',
      redirect: 'manual',
      signal: AbortSignal.timeout(20_000),
      headers: {Accept: 'application/json', 'User-Agent': 'ALEX research bibliography (https://github.com/RISEInfoSec/Alex)'},
    });
    headers = Object.fromEntries(RESPONSE_HEADERS.flatMap(name => {
      const value = response.headers.get(name);
      return value && /^[a-z0-9\-+ ,;=/.:]+$/i.test(value) && value.length <= 100 ? [[name, value]] : [];
    }));
    const bytes = await boundedBody(response);
    return {status: response.status, headers, body_hex: toHex(bytes), body_sha256: await hashBytes(bytes),
      outcome: response.status === 200 ? 'received' : 'held_http_status'};
  } catch (error) {
    return {status: response?.status ?? null, headers: headers ?? {}, outcome: 'held_uncertain_or_incomplete',
      reason: error.message === 'provider_response_size_limit' ? 'provider_response_size_limit' : 'response_not_durably_observed'};
  }
}

export async function readPilot(db, {includeBody = false} = {}) {
  const reservation = await db.prepare('SELECT request, at FROM pilot_reservations WHERE provider=?').bind(PROVIDER).first();
  if (!reservation) return {status: 'ready', attempts: 0, budget: 1, paid_budget: 0};
  const saved = await db.prepare('SELECT receipt, receipt_hash FROM pilot_outcomes WHERE provider=?').bind(PROVIDER).first();
  if (!saved) return {status: 'held_unresolved', attempts: 1, budget: 1, paid_budget: 0, reserved_at: reservation.at};
  if (await hash(saved.receipt) !== saved.receipt_hash) throw Error('provider_receipt_hash_mismatch');
  const {body_hex, ...receipt} = JSON.parse(saved.receipt);
  if (body_hex !== undefined && await hashBytes(fromHex(body_hex)) !== receipt.body_sha256) {
    throw Error('provider_response_hash_mismatch');
  }
  return {status: receipt.outcome, attempts: 1, budget: 1, paid_budget: 0, reserved_at: reservation.at,
    receipt: {...receipt, ...(includeBody ? {body_hex} : {})}, receipt_hash: saved.receipt_hash};
}

export async function runCrossrefPilot(db, implementationHash, send = fetch) {
  const descriptor = {namespace: NAMESPACE, provider: PROVIDER, method: 'GET', url: PILOT_URL, budget: 1,
    existing_public_id: 3198, timeout_seconds: 20, automatic_retries: 0};
  const reserved = await db.prepare('INSERT OR IGNORE INTO pilot_reservations VALUES(?,?,?) RETURNING provider')
    .bind(PROVIDER, canonical(descriptor), Date.now()).first();
  if (reserved) {
    const observed = await fetchCrossref(send);
    const receipt = canonical({...observed, observed_at: Date.now()});
    await db.prepare('INSERT INTO pilot_outcomes VALUES(?,?,?)').bind(PROVIDER, receipt, await hash(receipt)).run();
  }
  const state = await readPilot(db, {includeBody: true});
  if (state.status !== 'received') return state;
  const {body_hex: raw, ...receipt} = state.receipt;
  const result = {...state, receipt};
  let item;
  try {
    const decoded = new TextDecoder('utf-8', {fatal: true}).decode(fromHex(raw));
    item = JSON.parse(decoded)?.message;
  } catch {
    return {...result, downstream: {disposition: 'held', reason: 'malformed_provider_response'}};
  }
  if (canonicalDoi(item?.DOI) !== PILOT_DOI) {
    return {...result, downstream: {disposition: 'held', reason: 'response_doi_mismatch'}};
  }
  const request = {provider: 'api.crossref.org', operation: 'GET-json', contract: 'alex-stage2-recorded-v1',
    input: {url: PILOT_URL, params: {}}};
  const response = {status: 200, body: {message: item}};
  const capture = await retainCapture(db, {source: PROVIDER, collection: 'crossref-one-request-pilot',
    request, response, response_sha256: await digest(response)}, implementationHash);
  const downstream = await readCapture(db, capture.id);
  return {...result, downstream: {...downstream, disposition: 'held', reason: 'existing_public_record', public_id: 3198}};
}

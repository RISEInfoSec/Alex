"""One transactional authority for fixture processing and preview publication.

No HTTP client, credential lookup, production path or provider adapter is included.
The durable outbox is the preview authority; JSON/CSV are replaceable projections.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import time
import uuid
from contextlib import contextmanager

from alex.editorial_exclusions import exclusion_keys

REQUIRED_CHECKS = ('metadata', 'access', 'format', 'relevance', 'quality')
SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS candidates (
 id TEXT PRIMARY KEY, identity TEXT NOT NULL UNIQUE, payload TEXT NOT NULL,
 content_hash TEXT NOT NULL, state TEXT NOT NULL
 CHECK(state IN ('discovered','ingested','deduplicated','awaiting_review','held','failed','approved','rejected','previewed')));
CREATE TABLE IF NOT EXISTS aliases (
 identity TEXT PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES candidates(id));
CREATE TABLE IF NOT EXISTS discoveries (
 source TEXT NOT NULL, receipt TEXT NOT NULL, payload_hash TEXT NOT NULL,
 candidate_id TEXT NOT NULL REFERENCES candidates(id), PRIMARY KEY(source,receipt));
CREATE TABLE IF NOT EXISTS jobs (
 id INTEGER PRIMARY KEY, candidate_id TEXT NOT NULL REFERENCES candidates(id),
 stage TEXT NOT NULL CHECK(stage IN ('ingest','deduplicate','checks','preview')),
 status TEXT NOT NULL CHECK(status IN ('ready','running','done','failed')),
 lease TEXT, lease_until REAL, attempts INTEGER NOT NULL DEFAULT 0,
 UNIQUE(candidate_id,stage));
CREATE TABLE IF NOT EXISTS attempt_events (
 id INTEGER PRIMARY KEY, job_id INTEGER NOT NULL REFERENCES jobs(id), lease TEXT NOT NULL,
 event TEXT NOT NULL, at REAL NOT NULL, detail TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS checks (
 candidate_id TEXT NOT NULL REFERENCES candidates(id), content_hash TEXT NOT NULL,
 name TEXT NOT NULL, result TEXT NOT NULL CHECK(result IN ('pass','hold','fail')),
 evidence TEXT NOT NULL, PRIMARY KEY(candidate_id,content_hash,name));
CREATE TABLE IF NOT EXISTS decisions (
 id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL UNIQUE REFERENCES candidates(id),
 content_hash TEXT NOT NULL, verdict TEXT NOT NULL CHECK(verdict IN ('approve','reject','hold')),
 actor TEXT NOT NULL, reason TEXT NOT NULL, at REAL NOT NULL);
CREATE TABLE IF NOT EXISTS publications (
 candidate_id TEXT PRIMARY KEY REFERENCES candidates(id), decision_id TEXT NOT NULL UNIQUE REFERENCES decisions(id),
 content_hash TEXT NOT NULL, record TEXT NOT NULL, at REAL NOT NULL);
CREATE TRIGGER IF NOT EXISTS publication_gate BEFORE INSERT ON publications
WHEN NOT EXISTS (
 SELECT 1 FROM decisions d JOIN candidates c ON c.id=d.candidate_id
 WHERE d.id=NEW.decision_id AND d.candidate_id=NEW.candidate_id AND d.verdict='approve'
 AND d.content_hash=NEW.content_hash AND c.content_hash=NEW.content_hash AND c.state='approved'
 AND (SELECT COUNT(*) FROM checks k WHERE k.candidate_id=c.id AND k.content_hash=c.content_hash
 AND k.result='pass' AND k.name IN ('metadata','access','format','relevance','quality'))=5)
BEGIN SELECT RAISE(ABORT,'publication_gate'); END;
"""


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def identities(record):
    # Reuse ALEX's Unicode/title/year and DOI normalization. A landing-page URL
    # alone is not a paper identity: FIRST fragments can contain distinct papers.
    keys = exclusion_keys(record)
    strong = sorted(k for k in keys if k.startswith('doi:'))
    bib = sorted(k for k in keys if k.startswith('title-year:'))
    if not bib:
        raise ValueError('title_and_year_required_for_fixture')
    return strong + bib


class Store:
    def __init__(self, path, *, candidate_prefix='fixture-'):
        self.candidate_prefix = candidate_prefix
        self.path = Path(path).resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        self.db.row_factory = sqlite3.Row
        self.db.execute('PRAGMA foreign_keys=ON')
        self.db.execute('PRAGMA journal_mode=WAL')
        self.db.execute('PRAGMA synchronous=FULL')
        self.db.executescript(SCHEMA)
        for table in ('attempt_events', 'checks', 'decisions', 'publications', 'discoveries'):
            for operation in ('UPDATE', 'DELETE'):
                self.db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{operation} BEFORE {operation} ON {table} BEGIN SELECT RAISE(ABORT,'immutable_evidence'); END")

    def close(self):
        self.db.close()

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def enqueue(self, candidate_id, stage):
        self.db.execute("INSERT OR IGNORE INTO jobs(candidate_id,stage,status) VALUES (?,?,'ready')", (candidate_id, stage))

    def discover(self, source, receipt, record):
        payload = canonical(record)
        content_hash = digest(record)
        keys = identities(record)
        with self.transaction():
            previous = self.db.execute('SELECT * FROM discoveries WHERE source=? AND receipt=?', (source, receipt)).fetchone()
            if previous:
                if previous['payload_hash'] != content_hash:
                    raise ValueError('receipt_content_conflict')
                return previous['candidate_id']
            matches = {r[0] for key in keys for r in self.db.execute('SELECT candidate_id FROM aliases WHERE identity=?', (key,))}
            if len(matches) > 1:
                raise ValueError('identity_conflict_requires_review')
            if matches:
                candidate_id = matches.pop()
                old = self.db.execute('SELECT payload FROM candidates WHERE id=?', (candidate_id,)).fetchone()
                # DOI/title formatting variants replay safely; new substantive
                # content cannot inherit an existing decision without review.
                a, b = json.loads(old[0]), dict(record)
                for value in (a, b):
                    value.pop('doi', None)
                    value.pop('title', None)
                if canonical(a) != canonical(b):
                    raise ValueError('content_conflict_requires_review')
                old_doi = next((k for k in identities(json.loads(old[0])) if k.startswith('doi:')), None)
                new_doi = next((k for k in keys if k.startswith('doi:')), None)
                old_bib = {k for k in identities(json.loads(old[0])) if k.startswith('title-year:')}
                new_bib = {k for k in keys if k.startswith('title-year:')}
                if old_doi != new_doi or old_bib != new_bib:
                    raise ValueError('conflicting_doi_requires_review')
            else:
                candidate_id = self.candidate_prefix + hashlib.sha256(keys[0].encode()).hexdigest()[:24]
                self.db.execute('INSERT INTO candidates VALUES (?,?,?,?,?)', (candidate_id, keys[0], payload, content_hash, 'discovered'))
                self.enqueue(candidate_id, 'ingest')
            for key in keys:
                self.db.execute('INSERT OR IGNORE INTO aliases VALUES (?,?)', (key, candidate_id))
            self.db.execute('INSERT INTO discoveries VALUES (?,?,?,?)', (source, receipt, content_hash, candidate_id))
            return candidate_id

    def claim(self, now=None, lease_seconds=60, max_attempts=3):
        now = time.time() if now is None else now
        with self.transaction():
            expired = self.db.execute("SELECT * FROM jobs WHERE status='running' AND lease_until<=?", (now,)).fetchall()
            for job in expired:
                status = 'ready' if job['attempts'] < max_attempts else 'failed'
                self.db.execute('UPDATE jobs SET status=?,lease=NULL,lease_until=NULL WHERE id=?', (status, job['id']))
                self.event(job, 'lease_expired', now, status)
            job = self.db.execute("SELECT * FROM jobs WHERE status='ready' ORDER BY id LIMIT 1").fetchone()
            if not job:
                return None
            lease = str(uuid.uuid4())
            self.db.execute("UPDATE jobs SET status='running',lease=?,lease_until=?,attempts=attempts+1 WHERE id=?", (lease, now + lease_seconds, job['id']))
            job = dict(self.db.execute('SELECT * FROM jobs WHERE id=?', (job['id'],)).fetchone())
            self.event(job, 'claimed', now, 'fixture_only')
            return job

    def event(self, job, event, now, detail):
        self.db.execute('INSERT INTO attempt_events(job_id,lease,event,at,detail) VALUES (?,?,?,?,?)', (job['id'], job['lease'], event, now, detail))

    def complete(self, job, provider_fixture, excluded_keys=(), now=None):
        now = time.time() if now is None else now
        with self.transaction():
            current = self.db.execute('SELECT * FROM jobs WHERE id=?', (job['id'],)).fetchone()
            if current['status'] != 'running' or current['lease'] != job['lease'] or current['lease_until'] <= now:
                raise ValueError('lost_lease')
            candidate = self.db.execute('SELECT * FROM candidates WHERE id=?', (job['candidate_id'],)).fetchone()
            record = json.loads(candidate['payload'])
            if digest(record) != candidate['content_hash']:
                raise ValueError('candidate_hash_mismatch')
            stage = job['stage']
            state = {'ingest':'ingested', 'deduplicate':'deduplicated'}.get(stage)
            if stage == 'ingest':
                if not record.get('title') or not record.get('year'):
                    raise ValueError('invalid_metadata')
                self.enqueue(candidate['id'], 'deduplicate')
            elif stage == 'deduplicate':
                if exclusion_keys(record) & set(excluded_keys):
                    state = 'held'
                else:
                    self.enqueue(candidate['id'], 'checks')
            elif stage == 'checks':
                results = []
                # Fixture responses are explicitly content-bound. There is no
                # default pass, provider fallback or interpretation of HTTP 200.
                bound = provider_fixture.get(candidate['content_hash'], {})
                if not isinstance(bound, dict):
                    bound = {}
                for name in REQUIRED_CHECKS:
                    check = bound.get(name)
                    valid = isinstance(check, dict) and check.get('result') in ('pass','hold','fail') and isinstance(check.get('evidence'), str) and bool(check['evidence'])
                    result = check['result'] if valid else 'hold'
                    evidence = check['evidence'] if valid else 'missing_or_invalid_fixture_evidence'
                    self.db.execute('INSERT INTO checks VALUES (?,?,?,?,?)', (candidate['id'], candidate['content_hash'], name, result, evidence))
                    results.append(result)
                state = 'failed' if 'fail' in results else 'held' if 'hold' in results else 'awaiting_review'
            elif stage == 'preview':
                decision = self.db.execute('SELECT * FROM decisions WHERE candidate_id=?', (candidate['id'],)).fetchone()
                public = dict(record, id=candidate['id'])
                self.db.execute('INSERT INTO publications VALUES (?,?,?,?,?)', (candidate['id'], decision['id'], candidate['content_hash'], canonical(public), now))
                state = 'previewed'
            else:
                raise ValueError('unknown_stage')
            self.db.execute('UPDATE candidates SET state=? WHERE id=?', (state, candidate['id']))
            self.db.execute("UPDATE jobs SET status='done',lease_until=NULL WHERE id=?", (job['id'],))
            self.event(job, 'completed', now, state)

    def work(self, provider_fixture, excluded_keys=(), now=None, after_claim=None):
        count = 0
        while (job := self.claim(now=now)) is not None:
            if after_claim:
                after_claim(job)
            self.complete(job, provider_fixture, excluded_keys, now=now)
            count += 1
        return count

    def decide(self, candidate_id, content_hash, verdict, actor, reason, decision_id):
        if verdict not in ('approve','reject','hold') or not actor.strip() or not reason.strip():
            raise ValueError('explicit_editorial_receipt_required')
        with self.transaction():
            old = self.db.execute('SELECT * FROM decisions WHERE candidate_id=?', (candidate_id,)).fetchone()
            if old:
                if (old['id'],old['content_hash'],old['verdict'],old['actor'],old['reason']) != (decision_id,content_hash,verdict,actor,reason):
                    raise ValueError('decision_conflict_requires_review')
                return
            candidate = self.db.execute('SELECT * FROM candidates WHERE id=?', (candidate_id,)).fetchone()
            if not candidate or candidate['content_hash'] != content_hash:
                raise ValueError('stale_review_content')
            if candidate['state'] not in ('awaiting_review','held','failed'):
                raise ValueError('candidate_not_ready_for_editorial_review')
            if verdict == 'approve' and candidate['state'] != 'awaiting_review':
                raise ValueError('checks_not_passed')
            self.db.execute('INSERT INTO decisions VALUES (?,?,?,?,?,?,?)', (decision_id, candidate_id, content_hash, verdict, actor, reason, time.time()))
            self.db.execute('UPDATE candidates SET state=? WHERE id=?', ({'approve':'approved','reject':'rejected','hold':'held'}[verdict], candidate_id))
            if verdict == 'approve':
                self.enqueue(candidate_id, 'preview')

    def export_preview(self, directory):
        out = Path(directory).resolve()
        if out == self.path.parent or self.path.is_relative_to(out):
            raise ValueError('preview_directory_must_not_contain_private_database')
        with self.transaction():
            papers = [json.loads(r[0]) for r in self.db.execute('SELECT record FROM publications ORDER BY candidate_id')]
        out.mkdir(parents=True, exist_ok=True)
        documents = {'papers.json': json.dumps(papers, ensure_ascii=False, indent=2)+'\n'}
        stream = io.StringIO()
        fields = sorted({k for row in papers for k in row}) or ['id']
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(papers)
        documents['papers.csv'] = stream.getvalue()
        for name, text in documents.items():
            tmp = out / ('.'+name+'.'+uuid.uuid4().hex)
            with tmp.open('w') as handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp, out/name)
        return papers

    def counts(self):
        return {table:self.db.execute('SELECT COUNT(*) FROM '+table).fetchone()[0] for table in ('candidates','discoveries','jobs','attempt_events','checks','decisions','publications')}

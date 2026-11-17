"""Actual check execution and explicit staged reviewer receipts over Stage 1."""
from __future__ import annotations

import json
from pathlib import Path
import time

from stage1.engine import Store, canonical, digest
from stage2.checks import CheckRunner
from stage2.effects import EffectLedger


class ProcessingStore(Store):
    def __init__(self, path, *, root, reviewers):
        super().__init__(path, candidate_prefix='alex-')
        if not reviewers or any(not isinstance(r, str) or not r.strip() for r in reviewers):
            raise ValueError('explicit_staging_reviewer_allowlist_required')
        self.reviewers = frozenset(reviewers)
        self.check_runner = CheckRunner(root)
        self.effects = EffectLedger(self.db)
        self.db.executescript("""
        CREATE TABLE IF NOT EXISTS retained_documents(
          candidate_id TEXT PRIMARY KEY REFERENCES candidates(id),
          content_hash TEXT NOT NULL, receipt TEXT NOT NULL, receipt_hash TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS processing_policy(
          id INTEGER PRIMARY KEY CHECK(id=1), policy_hash TEXT NOT NULL);
        CREATE TRIGGER IF NOT EXISTS retained_document_no_update BEFORE UPDATE ON retained_documents
          BEGIN SELECT RAISE(ABORT,'immutable_document'); END;
        CREATE TRIGGER IF NOT EXISTS retained_document_no_delete BEFORE DELETE ON retained_documents
          BEGIN SELECT RAISE(ABORT,'immutable_document'); END;
        CREATE TABLE IF NOT EXISTS intake_holds(
          receipt_hash TEXT PRIMARY KEY, source TEXT NOT NULL, record TEXT NOT NULL, reason TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS source_outcomes(
          receipt_hash TEXT PRIMARY KEY, source TEXT NOT NULL, status TEXT NOT NULL,
          discovered INTEGER NOT NULL, held INTEGER NOT NULL);
        """)
        existing = self.db.execute('SELECT policy_hash FROM processing_policy WHERE id=1').fetchone()
        if existing and existing[0] != self.check_runner.policy_hash:
            self.close()
            raise ValueError('policy_changed_requires_new_staging_run')
        self.db.execute('INSERT OR IGNORE INTO processing_policy VALUES(1,?)', (self.check_runner.policy_hash,))

    def discover_saved(self, source, receipt, record, document=None):
        candidate_id = self.discover(source, receipt, record)
        if document is not None:
            content_hash = digest(record)
            if document.get('candidate_content_hash') != content_hash:
                raise ValueError('document_not_bound_to_candidate')
            with self.transaction():
                old = self.db.execute('SELECT * FROM retained_documents WHERE candidate_id=?', (candidate_id,)).fetchone()
                if old and (old['content_hash'] != content_hash or old['receipt_hash'] != digest(document)):
                    raise ValueError('retained_document_conflict')
                self.db.execute('INSERT OR IGNORE INTO retained_documents VALUES(?,?,?,?)',
                                (candidate_id, content_hash, canonical(document), digest(document)))
        return candidate_id

    def complete(self, job, *, now=None):
        candidate = self.db.execute('SELECT * FROM candidates WHERE id=?', (job['candidate_id'],)).fetchone()
        record = json.loads(candidate['payload'])
        results = {}
        if job['stage'] == 'checks':
            receipt = self.db.execute('SELECT * FROM retained_documents WHERE candidate_id=?', (candidate['id'],)).fetchone()
            document = None
            if receipt:
                document = json.loads(receipt['receipt'])
                if digest(document) != receipt['receipt_hash'] or receipt['content_hash'] != candidate['content_hash']:
                    raise ValueError('retained_document_hash_mismatch')
            results = self.check_runner.evaluate(record, document)
        return super().complete(job, results, self.check_runner.excluded, now=now)

    def work(self, *, now=None, after_claim=None, max_jobs=100):
        if not 1 <= max_jobs <= 1000:
            raise ValueError('invalid_job_bound')
        count = 0
        while count < max_jobs and (job := self.claim(now=now)) is not None:
            if after_claim:
                after_claim(job)
            self.complete(job, now=now)
            count += 1
        return count

    def review_packet(self):
        candidates = []
        for row in self.db.execute('SELECT * FROM candidates ORDER BY id'):
            candidates.append({'candidate_id': row['id'], 'content_hash': row['content_hash'],
                               'state': row['state'], 'record': json.loads(row['payload']),
                               'checks': [dict(c) for c in self.db.execute('SELECT name,result,evidence FROM checks WHERE candidate_id=? ORDER BY name', (row['id'],))],
                               'editorial_examples': self.editorial_examples(json.loads(row['payload']))})
        return {'schema_version': 1, 'policy_hash': self.check_runner.policy_hash,
                'candidates': candidates, 'decision_authority': 'explicit_staging_review_receipt'}

    def editorial_examples(self, record):
        from alex.utils.text import normalize_title
        words = set(normalize_title(record.get('title', '')).split())
        examples = []
        for item in self.check_runner.feedback.get('audit_examples', []):
            shared = words & set(normalize_title(item.get('title', '')).split())
            if shared and item.get('human_decision') in ('keep', 'remove'):
                examples.append((len(shared), item))
        result = []
        for label in ('keep', 'remove'):
            matches = sorted((x for x in examples if x[1]['human_decision'] == label),
                             key=lambda x: (-x[0], x[1].get('title', '')))[:3]
            # Audit reasons are not represented as user-supplied reasons.
            result.extend({k: item.get(k) for k in ('title', 'doi', 'human_decision', 'content_sha256')}
                          for _, item in matches)
        return result

    def review(self, receipt):
        if receipt.get('actor') not in self.reviewers:
            raise ValueError('staging_reviewer_not_allowed')
        if receipt.get('policy_hash') != self.check_runner.policy_hash:
            raise ValueError('stale_review_policy')
        # This interface is for an authenticated local operator in private
        # staging. It is not an HTTP endpoint or a production identity claim.
        self.decide(receipt['candidate_id'], receipt['content_hash'], receipt['verdict'],
                    receipt['actor'], receipt['reason'], receipt['id'])

    def status(self):
        return {'mode': 'isolated_recorded_evidence', 'policy_hash': self.check_runner.policy_hash,
                'counts': self.counts(),
                'states': {r[0]: r[1] for r in self.db.execute('SELECT state,count(*) FROM candidates GROUP BY state')},
                'effect_states': {r[0]: r[1] for r in self.db.execute('SELECT state,count(*) FROM external_effects GROUP BY state')},
                'job_states': {r[0]: r[1] for r in self.db.execute('SELECT status,count(*) FROM jobs GROUP BY status')},
                'failed_jobs': [dict(r) for r in self.db.execute("SELECT candidate_id,stage,attempts FROM jobs WHERE status='failed' ORDER BY id")],
                'intake_holds': self.db.execute('SELECT count(*) FROM intake_holds').fetchone()[0],
                'source_outcomes': [dict(r) for r in self.db.execute('SELECT source,status,discovered,held FROM source_outcomes ORDER BY receipt_hash')],
                'production_writes': False, 'live_provider_requests': 0}

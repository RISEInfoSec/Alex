"""Durable effect reservations; uncertainty never becomes an automatic retry.

Transport is supplied by a recorded-response client in Stage 2. A future live
transport needs its own authorization, provider pacing and credential boundary.
"""
from __future__ import annotations

import json
import math
import re
import sqlite3
import time
import uuid
from contextlib import contextmanager

from stage1.engine import canonical, digest

SCHEMA = """
CREATE TABLE IF NOT EXISTS external_effects(
 request_hash TEXT PRIMARY KEY, request TEXT NOT NULL, state TEXT NOT NULL,
 token TEXT, attempts INTEGER NOT NULL DEFAULT 0, response TEXT,
 response_hash TEXT, not_before REAL NOT NULL DEFAULT 0, reason TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS external_effect_events(
 id INTEGER PRIMARY KEY, request_hash TEXT NOT NULL REFERENCES external_effects(request_hash),
 event TEXT NOT NULL, receipt TEXT NOT NULL, at REAL NOT NULL);
CREATE TRIGGER IF NOT EXISTS effect_event_no_update BEFORE UPDATE ON external_effect_events
 BEGIN SELECT RAISE(ABORT,'immutable_effect_event'); END;
CREATE TRIGGER IF NOT EXISTS effect_event_no_delete BEFORE DELETE ON external_effect_events
 BEGIN SELECT RAISE(ABORT,'immutable_effect_event'); END;
"""


class EffectHeld(RuntimeError):
    """No new send is permitted; inspect the durable outcome and receipt."""


class EffectLedger:
    def __init__(self, connection, *, max_attempts=3):
        if type(max_attempts) is not int or not 1 <= max_attempts <= 10:
            raise ValueError('invalid_effect_attempt_bound')
        self.db = connection
        self.db.executescript(SCHEMA)
        self.max_attempts = max_attempts

    @contextmanager
    def transaction(self):
        self.db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self.db.execute('COMMIT')
        except BaseException:
            self.db.execute('ROLLBACK')
            raise

    def event(self, key, event, receipt, now):
        self.db.execute('INSERT INTO external_effect_events(request_hash,event,receipt,at) VALUES(?,?,?,?)',
                        (key, event, canonical(receipt), now))

    def request(self, request, transport, validate, *, now=None):
        now = time.time() if now is None else now
        # Descriptors are public request identities, never headers/credentials.
        if set(request) != {'provider', 'operation', 'input', 'contract'}:
            raise ValueError('invalid_request_descriptor')
        forbidden = ('authorization', 'api_key', 'token', 'cookie', 'password', 'secret')
        def inspect(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if any(term in str(key).lower() for term in forbidden):
                        raise ValueError('credential_in_request_descriptor')
                    inspect(item)
            elif isinstance(value, list):
                for item in value:
                    inspect(item)
        inspect(request)
        key = digest(request)
        with self.transaction():
            old = self.db.execute('SELECT * FROM external_effects WHERE request_hash=?', (key,)).fetchone()
            if old:
                if old['request'] != canonical(request):
                    raise ValueError('request_hash_conflict')
                if old['state'] == 'succeeded':
                    response = json.loads(old['response'])
                    if digest(response) != old['response_hash']:
                        raise ValueError('response_hash_mismatch')
                    validate(response)
                    return response
                if old['state'] != 'ready' or now < old['not_before'] or old['attempts'] >= self.max_attempts:
                    # A prior running token might still be executing. Do not
                    # steal it or reinterpret silence as a confirmed failure.
                    raise EffectHeld(old['reason'] or 'outcome_unresolved')
            else:
                self.db.execute('INSERT INTO external_effects(request_hash,request,state,reason) VALUES(?,?,?,?)',
                                (key, canonical(request), 'ready', 'not_started'))
            token = str(uuid.uuid4())
            self.db.execute("UPDATE external_effects SET state='running',token=?,attempts=attempts+1,reason='outcome_unresolved' WHERE request_hash=?", (token, key))
            self.event(key, 'reserved_before_transport', {'token': token}, now)
        # The reservation commits before dispatch. Process death at any later
        # boundary leaves an unresolved effect, even if a response was lost.
        try:
            response = transport(request)
        except BaseException:
            with self.transaction():
                self.db.execute("UPDATE external_effects SET state='held',reason='transport_outcome_unknown' WHERE request_hash=? AND token=?", (key, token))
                self.event(key, 'outcome_unknown', {}, now)
            raise
        response_text, response_hash = canonical(response), digest(response)
        status = response.get('status') if isinstance(response, dict) else None
        valid = False
        try:
            if status == 200:
                validate(response)
                valid = True
        except (ValueError, TypeError, KeyError):
            pass
        retry_after = response.get('retry_after_seconds', 0) if isinstance(response, dict) else 0
        if not isinstance(retry_after, (int, float)) or not math.isfinite(retry_after) or retry_after < 0:
            retry_after = 0
        reason = 'complete' if valid else 'access_denied' if status in (401, 403) else 'quota_hold' if status == 429 else 'invalid_or_failed_response'
        with self.transaction():
            current = self.db.execute('SELECT token,state FROM external_effects WHERE request_hash=?', (key,)).fetchone()
            if current['token'] != token or current['state'] != 'running':
                raise EffectHeld('superseded_effect_token')
            self.db.execute('UPDATE external_effects SET state=?,response=?,response_hash=?,not_before=?,reason=? WHERE request_hash=?',
                            ('succeeded' if valid else 'held', response_text, response_hash,
                             now + retry_after, reason, key))
            self.event(key, 'response_retained', {'response_hash': response_hash, 'status': status,
                                                 'valid': valid, 'reason': reason}, now)
        if not valid:
            raise EffectHeld(reason)
        return response

    def authorize_retry(self, request, receipt, *, now=None):
        """Explicit reconciliation, never a background retry after uncertainty.

        Stage 2 receipts concern recorded transports only. A real provider
        receipt must come from the authorized operator/provider reconciliation.
        """
        now = time.time() if now is None else now
        key = digest(request)
        if (receipt.get('request_hash') != key or not receipt.get('id') or
                not receipt.get('actor') or not receipt.get('reason') or
                receipt.get('finding') not in ('confirmed_not_sent', 'retry_received_failure')):
            raise ValueError('explicit_reconciliation_receipt_required')
        with self.transaction():
            old = self.db.execute('SELECT * FROM external_effects WHERE request_hash=?', (key,)).fetchone()
            if not old or old['state'] not in ('held', 'running'):
                raise ValueError('no_unresolved_effect')
            if now < old['not_before'] or old['attempts'] >= self.max_attempts:
                raise EffectHeld('cooldown_or_attempt_bound')
            if old['reason'] in ('access_denied', 'quota_hold'):
                raise EffectHeld('provider_hold_requires_separate_authorization')
            if receipt['finding'] == 'retry_received_failure':
                if not old['response_hash'] or receipt.get('response_hash') != old['response_hash']:
                    raise ValueError('received_failure_evidence_required')
            elif old['response_hash'] or not re.fullmatch(r'[0-9a-f]{64}', str(receipt.get('evidence_sha256', ''))):
                raise ValueError('not_sent_evidence_required')
            self.event(key, 'operator_reconciliation', receipt, now)
            # Preserve original response bytes/history in the immutable event.
            self.event(key, 'prior_outcome', {'response': old['response'], 'response_hash': old['response_hash']}, now)
            self.db.execute("UPDATE external_effects SET state='ready',token=NULL,reason='explicit_retry_authorized' WHERE request_hash=?", (key,))

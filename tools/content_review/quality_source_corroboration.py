"""Read-only source corroboration for a possible core-term quality hold.

This verifies only that the exact reviewed abstract is present in a matching
publisher source. Existing holds can be inspected explicitly and are preserved.
This does not establish that an abstract is complete, write a checkpoint, pass
a gate, or authorize a decision or publication. Any eventual writer must
independently revalidate the source and current private decisions.
"""
from datetime import datetime, timezone
import hashlib
import re

from tools.content_review.quality_hold_rules import audit as audit_hold
from tools.content_review.source_gate_rules import audit as audit_source


def audit(row, collection, receipt, registry, *, now=None, inspect_existing_hold=False):
    now = now or datetime.now(timezone.utc)
    if type(inspect_existing_hold) is not bool:
        raise ValueError('Quality source inspection mode invalid')
    hold = audit_hold(row, registry)
    previous = row.get('preflight', {}).get('checks', {}).get('quality')
    existing = (inspect_existing_hold and isinstance(previous, dict) and previous.get('status') == 'held' and
                previous.get('content_sha256') == row.get('content_sha256') and isinstance(previous.get('checked_at'), str) and previous['checked_at'] and
                not previous.get('stale') and isinstance(previous.get('evidence'), dict) and bool(previous['evidence']))
    if hold.get('status') != 'verified_core_term_absence' and not existing:
        return {'status': 'held', 'reason': 'quality_hold_not_established', 'writes': 0}
    if existing:
        abstract = row.get('abstract')
        complete = (row.get('abstract_integrity_status') == 'verified_complete' or
                    isinstance(row.get('abstract_text_status'), str) and row['abstract_text_status'].startswith('cached_official_program_abstract'))
        if (not isinstance(abstract, str) or not re.fullmatch(r'[\x00-\x7f]*', abstract) or len(abstract.strip()) < 100 or
                not complete or row.get('abstract_truncated') or '[truncated]' in abstract):
            return {'status': 'held', 'reason': 'complete_reviewed_text_required', 'writes': 0}
    source = audit_source(row, collection, receipt, now=now)
    checks = source.get('checks', {})
    if not all(checks.get(g, {}).get('status') == 'passed' for g in ('access', 'metadata')):
        return {'status': 'held', 'reason': 'matching_publisher_evidence_required', 'writes': 0}
    proof = checks['metadata']['evidence']
    records = [x for x in receipt['result']['records'] if isinstance(x, dict) and
               x.get('collection') == collection and x.get('candidate_id') == row['candidate_id'] and
               x.get('content_sha256') == row['content_sha256']]
    evidence = [x for x in records[0]['evidence'] if isinstance(x, dict) and
                all(x.get(k) == proof[k] for k in ('text_sha256', 'body_sha256', 'requested_url', 'final_url', 'retrieved_at'))]
    if len(evidence) != 1:
        return {'status': 'held', 'reason': 'source_text_ambiguous', 'writes': 0}
    normalize = lambda value: re.sub(r'[ \t\r\n]+', ' ', value).strip(' \t\r\n')
    abstract = normalize(row['abstract'])
    text = normalize(evidence[0]['text'])
    if not abstract or abstract not in text:
        return {'status': 'held', 'reason': 'reviewed_abstract_not_in_source_text', 'writes': 0}
    result = {'status': 'source_text_corroborated', 'request_id': proof['request_id'],
              'source_text_sha256': proof['text_sha256'], 'abstract_sha256': hashlib.sha256(abstract.encode()).hexdigest(),
              'abstract_complete_verified': False, 'gate_passed': False, 'publication_authorized': False, 'writes': 0}
    if existing:
        result.update(existing_hold_preserved=True, core_absence_verified=False)
    return result

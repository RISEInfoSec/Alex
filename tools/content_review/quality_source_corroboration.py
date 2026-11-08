"""Read-only source corroboration for a possible core-term quality hold.

This verifies only that the exact reviewed abstract is present in a matching
publisher source. It does not establish that an abstract is complete, write a
checkpoint, pass a gate, or authorize a decision or publication. Any eventual
writer must independently revalidate the source and current private decisions.
"""
from datetime import datetime, timezone
import hashlib
import re

from tools.content_review.quality_hold_rules import audit as audit_hold
from tools.content_review.source_gate_rules import audit as audit_source


def audit(row, collection, receipt, registry, *, now=None):
    now = now or datetime.now(timezone.utc)
    hold = audit_hold(row, registry)
    if hold.get('status') != 'verified_core_term_absence':
        return {'status': 'held', 'reason': 'quality_hold_not_established', 'writes': 0}
    source = audit_source(row, collection, receipt, now=now)
    checks = source.get('checks', {})
    if not all(checks.get(g, {}).get('status') == 'passed' for g in ('access', 'metadata', 'format')):
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
    return {'status': 'source_text_corroborated', 'request_id': proof['request_id'],
            'source_text_sha256': proof['text_sha256'], 'abstract_sha256': hashlib.sha256(abstract.encode()).hexdigest(),
            'abstract_complete_verified': False, 'gate_passed': False, 'publication_authorized': False, 'writes': 0}

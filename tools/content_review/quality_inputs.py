"""Recover retained scoring inputs without changing reviewed content or decisions."""
import copy
from tools.content_review.paid_worker import digest, reviewed_digest


def restore_affiliations(row, upstream, *, source_proof, checked_at):
    if row.get('decision', 'pending') not in ('pending', 'unreviewed'):
        raise ValueError('Decided records require their separate accepted-final validation')
    if (digest(upstream) != row.get('source_record_sha256')
            or str(upstream.get('candidate_id')) != str(row.get('upstream_candidate_id'))):
        raise ValueError('Original upstream identity or fingerprint changed')
    if reviewed_digest(row) != row.get('content_sha256'):
        raise ValueError('Reviewed content changed')
    value = upstream.get('affiliations', '').strip()
    if not value or not all(source_proof.get(k) for k in ('receipt', 'body_sha256', 'inspection')):
        raise ValueError('Verified source affiliation evidence required')
    if row.get('affiliations') not in (None, '', value):
        raise ValueError('Conflicting existing affiliation')
    result = copy.deepcopy(row)
    if result.get('affiliations') == value:
        return result
    result.setdefault('quality_input_versions', []).append({
        'checked_at': checked_at, 'prior_affiliations': row.get('affiliations'),
        'prior_quality': copy.deepcopy(row.get('preflight', {}).get('checks', {}).get('quality')),
        'source_record_sha256': row['source_record_sha256'], 'source_proof': copy.deepcopy(source_proof),
        'reason': 'Restore original scoring input omitted by weekly manifest builder; original document corroborates affiliation.'})
    result['affiliations'] = value
    return result

"""Plan scarce registry work; never changes a score, decision or corpus."""
def plan(record):
    h = record.get('content_sha256')
    checks = record.get('preflight', {}).get('checks', {})
    if not h:
        return {'eligible': False, 'reason': 'missing_current_content_hash'}
    for name in ('format', 'access', 'duplicates'):
        check = checks.get(name, {})
        if check.get('status') != 'passed' or check.get('content_sha256') != h:
            return {'eligible': False, 'reason': name + '_evidence_first'}
    quality = checks.get('quality', {})
    if quality.get('content_sha256') != h:
        return {'eligible': False, 'reason': 'current_quality_inputs_first'}
    evidence = quality.get('evidence', {})
    status = evidence.get('quality_review_status') if isinstance(evidence, dict) else None
    if status in ('hold_core_term_gate', 'hold_relevance_floor'):
        return {'eligible': False, 'reason': 'independent_text_hard_gate_hold', 'terminal_rejection': False}
    if status == 'hold_missing_abstract' or not (record.get('abstract') or '').strip():
        return {'eligible': False, 'reason': 'recover_original_abstract_first'}
    if status not in ('human_quality_review', 'provisional_auto_threshold', 'hold_below_review_threshold'):
        return {'eligible': False, 'reason': 'quality_inputs_unresolved'}
    metadata = checks.get('metadata', {})
    if metadata.get('content_sha256') != h:
        return {'eligible': False, 'reason': 'current_official_metadata_first'}
    evidence = metadata.get('evidence', {})
    compared = evidence.get('comparison', {}) if isinstance(evidence, dict) else {}
    compared = compared if isinstance(compared, dict) else {}
    official = all(compared.get(k) is True for k in ('title_matches', 'year_matches', 'author_families_match'))
    complete = metadata.get('full_author_reconciliation', {}).get('status') == 'passed'
    if metadata.get('status') != 'passed' and not (official and complete):
        return {'eligible': False, 'reason': 'official_metadata_reconciliation_first'}
    return {'eligible': True, 'reason': 'alternative_enrichment_first_openalex_targeted_fallback',
            'citation_sensitive_score': status == 'hold_below_review_threshold',
            'automatic_openalex_request': False}

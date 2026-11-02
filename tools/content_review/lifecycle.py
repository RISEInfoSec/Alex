"""Durable candidate lifecycle. No network, scoring, decisions or corpus writes.

Actual attempts are appended explicitly; observing a hold never invents an attempt.
Unnumbered discoveries stay in their existing raw inventories.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import json
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

LEDGER = 'config/content_review_candidate_lifecycle.json'
POLICY = 'config/content_review_lifecycle_policy.json'
INACTIVE = {'stable_quality_failure', 'awaiting_software_support', 'access_restricted',
            'retired_unresolved', 'operator_action_required'}
GATES = ('format', 'access', 'metadata', 'duplicates', 'quality', 'schema')
DEFAULT_POLICY = dict(version=1, initial_check_warning_hours=48,
    retry_days_after_initial=[1, 3, 7, 14], maximum_total_attempts=5,
    maximum_failure_age_days=30, supported_resource_types=['research_paper'],
    capability_revision='research-paper-export-v1', permission_revision='existing-access-policy-v1')

def instant(value):
    if not value:
        return None
    try:
        d = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None

def stamp(value=None):
    return (instant(value) if isinstance(value, str) else value or datetime.now(timezone.utc)).isoformat()

def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

def current_pass(row, gate):
    c = row.get('preflight', {}).get('checks', {}).get(gate, {})
    return (c.get('status') == 'passed' and c.get('content_sha256') == row.get('content_sha256')
            and bool(c.get('checked_at')) and bool(c.get('evidence')) and not c.get('stale'))

def baseline(row, at):
    dates = [row.get('intake_at'), row.get('discovered_at'), row.get('assessment_date'),
             row.get('source_observation', {}).get('first_seen_at')]
    dates += [c.get('checked_at') for c in row.get('preflight', {}).get('checks', {}).values()]
    return min([instant(d) for d in dates if instant(d)] or [at])

def evidence_key(row, policy):
    """Explicit substantive changes only. A heartbeat/checked_at is not a new version."""
    checks = row.get('preflight', {}).get('checks', {})
    return digest(dict(content=row.get('content_sha256'), source=row.get('source_record_sha256'),
        source_revision=row.get('lifecycle_evidence_revision'),
        access_revision=row.get('access_decision', {}).get('evidence_revision'),
        policy=policy['version'], capability=policy['capability_revision'],
        permission=policy['permission_revision'],
        quality_input_revision=checks.get('quality', {}).get('input_revision')))

def set_state(entry, state, reason, at, next_action, reconsider=None, retry=None):
    if entry.get('state') != state or entry.get('reason') != reason:
        entry.setdefault('history', []).append(dict(at=stamp(at), event='state_changed',
            previous=entry.get('state'), state=state, reason=reason, cycle=entry['cycle']))
        entry['state_changed_at'] = stamp(at)
    entry.update(state=state, reason=reason, next_action=next_action,
        reconsideration_condition=reconsider, next_retry_at=stamp(retry) if retry else None,
        active=state not in INACTIVE and state != 'completed')
    return entry

def evaluate(row, prior=None, at=None, policy=None):
    at = instant(at) if isinstance(at, str) else at or datetime.now(timezone.utc)
    policy = {**DEFAULT_POLICY, **(policy or {})}
    entry = copy.deepcopy(prior) if prior else dict(candidate_id=row['candidate_id'],
        first_seen_at=stamp(baseline(row, at)), cycle=1, attempts=[], history=[],
        historical_attempt_count_unknown=any(c.get('checked_at') for c in
            row.get('preflight', {}).get('checks', {}).values()))
    key = evidence_key(row, policy)
    if prior and entry.get('evidence_key') != key:
        entry['history'].append(dict(event='reconsidered', at=stamp(at),
            previous_evidence_key=entry.get('evidence_key'), previous_state=entry.get('state'),
            reason='Relevant content, verified evidence, policy, capability or permission revision changed.'))
        entry['cycle'] += 1
        entry.pop('first_failure_at', None)
        entry.pop('retired_at', None)
        entry['reconsidered_at'] = stamp(at)
    entry.update(content_sha256=row.get('content_sha256'), evidence_key=key, title=row.get('title', ''),
        source_url=row.get('source_url', ''), identities={k:row.get(k) for k in ('doi','source_url','candidate_id')},
        last_evaluated_at=stamp(at))
    attempts = [a for a in entry['attempts'] if a.get('cycle') == entry['cycle']]
    entry['attempt_count'] = len(attempts)
    entry['last_attempt_at'] = max([a['at'] for a in entry['attempts']], default=None)
    checks = row.get('preflight', {}).get('checks', {})
    entry['last_check_at'] = max([c.get('checked_at') for c in checks.values() if c.get('checked_at')], default=None)
    entry['outstanding_checks'] = [g for g in GATES if not current_pass(row, g)]
    entry['initial_checks_overdue'] = (not any(c.get('checked_at') for c in checks.values())
        and not attempts and at - instant(entry['first_seen_at']) >= timedelta(hours=policy['initial_check_warning_hours']))
    if row.get('decision') in ('approved','rejected') or row.get('publication_status') == 'published_live_verified':
        return set_state(entry, 'completed', 'Existing decision or verified publication retained.', at,
            'Follow the existing decision/publication path; lifecycle does not reverse decisions.')
    # A terminal or parked disposition remains suppressed until a relevant change.
    if prior and prior.get('evidence_key') == key and prior.get('state') in INACTIVE:
        return entry
    if all(current_pass(row, g) for g in GATES):
        return set_state(entry, 'ready', 'All six current evidence-bound gates passed.', at,
            'Prepare recommendation and admit 1–20 cleared candidates.')
    access = row.get('access_decision', {})
    tlp = str(row.get('source_observation', {}).get('tlp', '')).upper()
    if tlp and tlp not in ('TLP:CLEAR', 'TLP:WHITE'):
        return set_state(entry, 'access_restricted', 'Observed FIRST restriction: ' + tlp, at,
            'Do not retrieve restricted material.', 'Verified permission or relevant access-policy change.')
    if access.get('verified') and access.get('status') == 'restricted':
        return set_state(entry, 'access_restricted', access.get('reason', 'Verified access restriction.'), at,
            'Retain metadata; stop access attempts.', 'Verified permission or relevant access-policy change.')
    if current_pass(row, 'format') and row.get('document_type') not in policy['supported_resource_types']:
        return set_state(entry, 'awaiting_software_support', 'Verified resource type has no supported export path: ' + str(row.get('document_type')), at,
            'Retain the actual resource type; do not spend on repeated downloads or paper-only classification.',
            'A compatible classifier/export capability revision becomes available.')
    q = checks.get('quality', {})
    qe = q.get('evidence', {})
    text = row.get('abstract', '') or ''
    complete = (len(text.strip()) >= 100 and not row.get('abstract_truncated')
        and not any(mark in text for mark in ('[…]','[truncated]'))
        and (row.get('abstract_text_status', '').startswith('cached_official_program_abstract')
             or row.get('abstract_integrity_status') == 'verified_complete'))
    if (q.get('content_sha256') == row.get('content_sha256') and q.get('checked_at') and not q.get('stale')
        and isinstance(qe, dict) and qe.get('quality_review_status') in ('hold_core_term_gate','hold_relevance_floor')
        and complete and all(current_pass(row, g) for g in ('format','access','duplicates'))):
        return set_state(entry, 'stable_quality_failure', qe['quality_review_status'] + ' on verified source and complete abstract inputs.', at,
            'Stop unchanged retries and enrichment; retain all evidence and prior decisions.',
            'Relevant content, verified scoring inputs, policy or an explicit decision changes.')
    failures = [a for a in attempts if a['outcome'] == 'temporary_failure']
    if failures:
        first = min(instant(a['at']) for a in failures)
        entry['first_failure_at'] = stamp(first)
        if len(attempts) >= policy['maximum_total_attempts'] or at - first >= timedelta(days=policy['maximum_failure_age_days']):
            entry['retired_at'] = stamp(at)
            return set_state(entry, 'retired_unresolved', 'Retry budget or 30-day failure window exhausted: ' + failures[-1]['reason'], at,
                'No further unchanged attempts; preserve the attempt ledger.', 'Substantive new evidence, a new version, restored access or a relevant software fix.')
        offset = policy['retry_days_after_initial'][min(len(attempts)-1, len(policy['retry_days_after_initial'])-1)]
        due = first + timedelta(days=offset)
        cooldowns = [instant(a.get('retry_not_before')) for a in failures if instant(a.get('retry_not_before'))]
        if cooldowns:
            due = max([due] + cooldowns)
        return set_state(entry, 'retry_scheduled', failures[-1]['reason'], at,
            'Retry only the unresolved stage when due; reuse unchanged successful checks.', retry=due)
    return set_state(entry, 'awaiting_initial_checks',
        'Initial mechanical checks incomplete; no new failed attempt inferred from a stored hold.', at,
        'Complete missing initial stages.' + (' Initial processing is overdue by the 48-hour policy.' if entry['initial_checks_overdue'] else ''))

def record_attempt(entry, *, attempt_id, at, stage, outcome, reason, evidence_ref,
                   retry_not_before=None):
    if outcome not in ('success', 'temporary_failure', 'unresolved') or not all((attempt_id, stage, reason, evidence_ref)):
        raise ValueError('An actual attempt requires identity, stage, outcome, reason and evidence reference')
    result = copy.deepcopy(entry)
    if any(a['attempt_id'] == attempt_id for a in result['attempts']):
        return result
    if result.get('state') in INACTIVE:
        raise ValueError('Reconsider the relevant change before attempting an inactive candidate')
    if not due(result, at):
        raise ValueError('Candidate retry is not due')
    result['attempts'].append(dict(attempt_id=attempt_id, at=stamp(at), stage=stage,
        outcome=outcome, reason=reason, evidence_ref=evidence_ref, cycle=result['cycle'],
        retry_not_before=retry_not_before))
    if outcome == 'success':
        result['last_progress_at'] = stamp(at)
    if outcome == 'unresolved':
        set_state(result, 'retired_unresolved', reason, instant(at),
            'No repeat of the same exhausted evidence search.', 'Substantive new evidence or verified identity resolution.')
    return result

def due(entry, at=None):
    at = instant(at) if isinstance(at, str) else at or datetime.now(timezone.utc)
    return (entry.get('state') in ('awaiting_initial_checks','retry_scheduled') and
            (not instant(entry.get('next_retry_at')) or instant(entry['next_retry_at']) <= at))

def is_suppressed(ledger, collection, candidate_id):
    return ledger.get('records', {}).get(collection + ':' + candidate_id, {}).get('state') in INACTIVE

def load(root, path, default):
    p = Path(root) / path
    return json.loads(p.read_text()) if p.exists() else copy.deepcopy(default)

def ensure_eligible(root, collection, candidate_id):
    e = load(root, LEDGER, {'records':{}})['records'].get(collection + ':' + candidate_id)
    if e and (e.get('state') in INACTIVE or (e.get('state') == 'retry_scheduled' and not due(e))):
        raise ValueError('Lifecycle prevents work: ' + e['state'] + ': ' + candidate_id)

def sync(root, at=None):
    root = Path(root); at = instant(at) if isinstance(at, str) else at or datetime.now(timezone.utc)
    policy = load(root, POLICY, DEFAULT_POLICY)
    ledger = load(root, LEDGER, dict(schema_version=1, records={}))
    registry = json.loads((root/'config/review_console.json').read_text())
    for col in registry['collections']:
        if col.get('adapter') not in ('soups','normalized'):
            continue
        path = root/'config'/col['manifest_url'].rsplit('/',1)[-1]
        if not path.exists():
            continue
        m = json.loads(path.read_text())
        rows = [r for r in m.get('records',[]) if isinstance(r.get('review_number'),int)] + m.get('preflight_records',[])
        for row in rows:
            if not row.get('candidate_id') or not row.get('content_sha256'):
                continue
            key = col['id'] + ':' + row['candidate_id']
            if key not in ledger['records'] and (row.get('decision') in ('approved','rejected') or row.get('publication_status')=='published_live_verified'):
                continue  # Existing archives stay authoritative; do not duplicate decided inventories.
            entry = evaluate(row, ledger['records'].get(key), at, policy)
            entry['evidence_location']='config/'+path.name+'#'+row['candidate_id']
            entry['collection'] = col['id']; ledger['records'][key] = entry
    ledger.update(updated_at=stamp(at), policy_version=policy['version'])
    ledger['counts'] = dict(Counter(r['state'] for r in ledger['records'].values()))
    ledger['source_counts'] = {c:dict(Counter(r['state'] for r in ledger['records'].values() if r['collection']==c))
        for c in sorted({r['collection'] for r in ledger['records'].values()})}
    return ledger

def save(root, ledger):
    p = Path(root)/LEDGER; tmp = p.with_suffix('.tmp')
    tmp.write_text(json.dumps(ledger, ensure_ascii=False, indent=2)+'\n'); tmp.replace(p)

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--root',type=Path,default=Path.cwd())
    p.add_argument('--write',action='store_true');p.add_argument('--run-id');a=p.parse_args()
    if a.write:
        from tools.content_review.discover_sources import require_lease
        require_lease(a.root,a.run_id)
    ledger=sync(a.root)
    if a.write:save(a.root,ledger)
    print(json.dumps(dict(updated_at=ledger['updated_at'],counts=ledger['counts'],source_counts=ledger['source_counts'])))

if __name__=='__main__':main()

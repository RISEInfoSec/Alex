"""Bounded pilot budget. Pure local accounting; no network, decisions or writes."""
from __future__ import annotations
import time


def candidate_limit(policy, qualifying_receipts, checkpoint_repairs=()):
    # Immutable receipts may later be contradicted by an independently recorded
    # checkpoint failure. A repair preserves the work, not the original success.
    invalid_runs = {r.get('affected_run_id') for r in checkpoint_repairs
                    if r.get('prior_integrity_claim_corrected') is True}
    seen = set()
    for r in qualifying_receipts:
        p = r.get('pilot', {})
        if not isinstance(p,dict):
            continue
        gates=p.get('newly_passed_checks')
        if not isinstance(gates,dict):
            gates={}
        useful_progress=(any(isinstance(gates.get(g),list) and gates[g]
                             for g in ('format','access','metadata','quality','schema'))
                         or any(isinstance(p.get(k),list) and p[k]
                                for k in ('all_six_completed','manual_admitted','actual_publications')))
        if (p.get('pilot_id') == policy['id'] and r.get('trigger') == 'schedule'
            and r.get('run_id') not in invalid_runs and p.get('promotion_eligible') is not False
            and r.get('native_terminal_verified') is True and r.get('status') == 'complete'
            and p.get('integrity_passed') is True and p.get('budget_compliant') is True
            and p.get('access_rules_preserved') is True and p.get('lease_conflicts') == 0
            and p.get('heartbeat_interval_compliant') is True and useful_progress
            and p.get('checkpoint_failures') == 0 and p.get('attempted_candidate_ids')
            and r.get('run_id')):
            seen.add(r['run_id'])
    return policy['subsequent_candidate_limit'] if len(seen) >= policy['initial_successful_passes'] else policy['initial_candidate_limit']


class Budget:
    def __init__(self, policy, limit, *, elapsed_at_start=0, clock=time.monotonic):
        if elapsed_at_start < 0 or limit not in (policy['initial_candidate_limit'], policy['subsequent_candidate_limit']):
            raise ValueError('Invalid elapsed time or candidate limit')
        self.policy, self.limit, self.clock = policy, limit, clock
        self.start = clock() - elapsed_at_start
        self.candidates = set()
        self.counts = {'source': 0, 'paid': 0, 'openalex': 0, 'local': 0}

    def remaining(self):
        return max(0, self.policy['total_runtime_seconds'] - self.policy['checkpoint_reserve_seconds'] - (self.clock() - self.start))

    def candidate(self, candidate_id):
        if not candidate_id or self.remaining() <= 0:
            raise RuntimeError('No candidate work budget')
        if candidate_id not in self.candidates and len(self.candidates) >= self.limit:
            raise RuntimeError('Candidate ceiling reached')
        self.candidates.add(candidate_id)

    def consume(self, kind, timeout=0):
        caps = {'source': self.policy['source_request_limit'], 'paid': self.policy['new_paid_classification_limit'],
                'openalex': self.policy['openalex_request_limit'], 'local': self.policy['local_candidate_limit']}
        if kind not in caps or timeout < 0:
            raise ValueError('Unknown work kind or negative timeout')
        if self.remaining() <= timeout or self.counts[kind] >= caps[kind]:
            raise RuntimeError('Work/time ceiling reached')
        if kind != 'local' and timeout <= 0:
            raise ValueError('Network work requires a bounded positive timeout')
        if kind != 'local' and timeout > self.policy['request_timeout_seconds']:
            raise ValueError('Request timeout exceeds policy')
        self.counts[kind] += 1
        # Existing executors must separately enforce origin pacing, provider holds,
        # exact-hash eligibility, shared lease and request transport limits.

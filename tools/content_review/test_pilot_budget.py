"""Regression checks for bounded pilot ceilings; no external requests."""
import unittest
from tools.content_review.pilot_budget import Budget, candidate_limit

P = dict(id='test', initial_candidate_limit=5, initial_successful_passes=2,
    subsequent_candidate_limit=10, total_runtime_seconds=720, checkpoint_reserve_seconds=120,
    source_request_limit=30, new_paid_classification_limit=5, openalex_request_limit=1,
    local_candidate_limit=200, request_timeout_seconds=20)

class PilotBudgetTests(unittest.TestCase):
    def test_candidate_identity_and_ceiling(self):
        b=Budget(P,5)
        for i in range(5): b.candidate(str(i))
        b.candidate('0')
        with self.assertRaises(RuntimeError): b.candidate('sixth')

    def test_request_caps(self):
        for kind, cap in [('source',30),('paid',5),('openalex',1),('local',200)]:
            b=Budget(P,5)
            for _ in range(cap): b.consume(kind, 20 if kind!='local' else 0)
            with self.assertRaises(RuntimeError): b.consume(kind,20 if kind!='local' else 0)

    def test_startup_elapsed_and_checkpoint_reserve(self):
        b=Budget(P,5,elapsed_at_start=581)
        with self.assertRaises(RuntimeError): b.consume('source',20)
        b=Budget(P,5,elapsed_at_start=601)
        with self.assertRaises(RuntimeError): b.candidate('x')

    def test_two_distinct_independently_verified_runs(self):
        r=dict(run_id='a',trigger='schedule',native_terminal_verified=True,status='complete',
            pilot=dict(pilot_id='test',integrity_passed=True,budget_compliant=True,
                access_rules_preserved=True,lease_conflicts=0,checkpoint_failures=0,
                attempted_candidate_ids=['x'],heartbeat_interval_compliant=True,
                newly_passed_checks={'metadata':['x']}))
        self.assertEqual(candidate_limit(P,[r,r]),5)
        self.assertEqual(candidate_limit(P,[r,dict(r,run_id='b')]),10)
        self.assertEqual(candidate_limit(P,[r,dict(r,run_id='b',native_terminal_verified=False)]),5)
        self.assertEqual(candidate_limit(P,[r,dict(r,run_id='b',trigger='manual')]),5)
        self.assertEqual(candidate_limit(P,[r,dict(r,run_id='b',pilot={**r['pilot'],
            'heartbeat_interval_compliant':False})]),5)
        self.assertEqual(candidate_limit(P,[r,dict(r,run_id='b',pilot={**r['pilot'],
            'newly_passed_checks':{}})]),5)

if __name__=='__main__': unittest.main()

import copy
import json
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from tools.content_review.lifecycle import (evaluate, record_attempt, due, DEFAULT_POLICY,
    ensure_eligible, save, sync, set_state)

NOW=datetime(2026,11,2,12,tzinfo=timezone.utc)
H='a'*64
def row():
    return dict(candidate_id='one',title='Original',content_sha256=H,review_number=1,
        source_url='https://example.org/paper',abstract='Complete substantive abstract. '*10,
        document_type='research_paper',abstract_integrity_status='verified_complete',
        intake_at='2026-10-01T12:00:00Z',preflight={'checks':{}})
def passed():
    return dict(status='passed',content_sha256=H,evidence='Actual source proof',checked_at=NOW.isoformat())
def attempt(e,n,at,outcome='temporary_failure',cooldown=None):
    return record_attempt(e,attempt_id='run-'+str(n),at=at,stage='source_resolution',outcome=outcome,
        reason='Publisher unavailable',evidence_ref='immutable/checkpoint/'+str(n),retry_not_before=cooldown)

class LifecycleTests(unittest.TestCase):
    def test_untouched_age_warns_never_retires(self):
        e=evaluate(row(),at=NOW)
        self.assertEqual(e['state'],'awaiting_initial_checks')
        self.assertTrue(e['initial_checks_overdue']);self.assertEqual(e['attempt_count'],0)
        self.assertTrue(due(e,NOW));self.assertFalse(e['historical_attempt_count_unknown'])

    def test_retry_offsets_cap_and_history(self):
        r=row();e=evaluate(r,at=NOW)
        for n,day,next_day in [(1,0,1),(2,1,3),(3,3,7),(4,7,14)]:
            t=NOW+timedelta(days=day);e=evaluate(r,attempt(e,n,t),t)
            self.assertEqual(e['state'],'retry_scheduled')
            self.assertEqual(datetime.fromisoformat(e['next_retry_at']),NOW+timedelta(days=next_day))
            self.assertFalse(due(e,t+timedelta(minutes=1)))
            with self.assertRaises(ValueError):attempt(e,'early',t+timedelta(minutes=1))
        e=evaluate(r,attempt(e,5,NOW+timedelta(days=14)),NOW+timedelta(days=14))
        self.assertEqual(e['state'],'retired_unresolved');self.assertFalse(due(e,NOW+timedelta(days=99)))
        self.assertEqual(len(e['attempts']),5)
        with self.assertRaises(ValueError):attempt(e,6,NOW+timedelta(days=99))

    def test_provider_cooldown_and_thirty_day_expiry(self):
        r=row();e=evaluate(r,at=NOW);later=NOW+timedelta(days=40)
        e=evaluate(r,attempt(e,1,NOW,cooldown=later.isoformat()),NOW)
        self.assertEqual(datetime.fromisoformat(e['next_retry_at']),later)
        e=evaluate(r,e,NOW+timedelta(days=30));self.assertEqual(e['state'],'retired_unresolved')
        self.assertEqual(len(e['attempts']),1)
        # A stale state label cannot bypass the age budget before the next sync.
        stale=copy.deepcopy(e);stale['state']='retry_scheduled';stale['next_retry_at']=NOW.isoformat()
        self.assertFalse(due(stale,NOW+timedelta(days=31)))

    def test_replay_does_not_spend_an_attempt(self):
        r=row();e=attempt(evaluate(r,at=NOW),1,NOW)
        self.assertEqual(len(attempt(e,1,NOW)['attempts']),1)

    def test_success_ready_and_no_mutation(self):
        r=row();original=copy.deepcopy(r);e=attempt(evaluate(r,at=NOW),1,NOW,'success')
        self.assertEqual(e['last_progress_at'],NOW.isoformat());self.assertEqual(r,original)
        r['preflight']['checks']={g:passed() for g in ('format','access','metadata','duplicates','quality','schema')}
        self.assertEqual(evaluate(r,e,NOW)['state'],'ready')

    def test_stable_verified_failure_and_bad_evidence_controls(self):
        r=row();r['preflight']['checks']={g:passed() for g in ('format','access','duplicates')}
        r['preflight']['checks']['quality']={**passed(),'status':'held','evidence':{'quality_review_status':'hold_core_term_gate'}}
        e=evaluate(r,at=NOW);self.assertEqual(e['state'],'stable_quality_failure');self.assertFalse(due(e,NOW))
        for change in ('missing_source','truncated','stale'):
            b=copy.deepcopy(r)
            if change=='missing_source':b['preflight']['checks'].pop('access')
            elif change=='truncated':b['abstract_truncated']=True
            else:b['preflight']['checks']['quality']['stale']=True
            self.assertEqual(evaluate(b,at=NOW)['state'],'awaiting_initial_checks')

    def test_access_types_and_reconsideration_require_change(self):
        r=row();r['source_observation']={'tlp':'TLP:AMBER'}
        e=evaluate(r,at=NOW);self.assertEqual(e['state'],'access_restricted')
        self.assertEqual(evaluate(r,e,NOW+timedelta(days=60))['state'],'access_restricted')
        r['source_observation']['tlp']='TLP:CLEAR';r['lifecycle_evidence_revision']='verified-permission-receipt'
        e=evaluate(r,e,NOW+timedelta(days=60));self.assertEqual(e['state'],'awaiting_initial_checks')
        self.assertEqual(e['cycle'],2);self.assertTrue(any(h['event']=='reconsidered' for h in e['history']))
        r['document_type']='technical_report';r['preflight']['checks']['format']=passed()
        e=evaluate(r,at=NOW);self.assertEqual(e['state'],'awaiting_software_support')
        policy={**DEFAULT_POLICY,'capability_revision':'reports-supported-v2','supported_resource_types':['research_paper','technical_report']}
        self.assertEqual(evaluate(r,e,NOW,policy)['state'],'awaiting_initial_checks')

    def test_decisions_and_evidence_changes_preserved(self):
        r=row();e=evaluate(r,at=NOW);e=attempt(e,1,NOW,'unresolved')
        self.assertEqual(evaluate(r,e,NOW)['state'],'retired_unresolved')
        r['content_sha256']='b'*64;e=evaluate(r,e,NOW);self.assertEqual(e['state'],'awaiting_initial_checks')
        self.assertEqual(len(e['attempts']),1);self.assertEqual(e['attempt_count'],0)
        e=set_state(e,'operator_action_required','Which verified edition?',NOW,'Choose edition','Authenticated edition decision.')
        self.assertFalse(due(e,NOW))
        r['decision']='approved';self.assertEqual(evaluate(r,e,NOW)['state'],'completed')

    def test_durable_suppression_guard_and_raw_discovery_not_promoted(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'config').mkdir();r=row()
            (root/'config/review_console.json').write_text(json.dumps({'collections':[{'id':'first','adapter':'normalized','manifest_url':'https://source/first_review_manifest.json'}]}))
            (root/'config/first_review_manifest.json').write_text(json.dumps({'records':[r,{**r,'candidate_id':'raw','review_number':None}]}))
            ledger=sync(root,NOW);self.assertEqual(list(ledger['records']),['first:one'])
            e=ledger['records']['first:one'];set_state(e,'retired_unresolved','Exhausted',NOW,'Stop','New evidence')
            save(root,ledger)
            with self.assertRaises(ValueError):ensure_eligible(root,'first','one')
            self.assertEqual(sync(root,NOW)['records']['first:one']['state'],'retired_unresolved')

if __name__=='__main__':unittest.main()

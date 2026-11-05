import unittest,json,tempfile
from pathlib import Path
from tools.content_review.operations import verified_completion,find_automation,AUTOMATION,expected_next
from tools.content_review.operations import runtime_checkpoint,save_runtime

class OperationsTests(unittest.TestCase):
    def test_completion_requires_native_terminal_schedule_and_matching_real_receipt(self):
        run=dict(id='run',recorded_status='completed',scheduled_for='2026-11-02T22:05:00Z',started_at='2026-11-02T22:05:02Z',completed_at='2026-11-02T22:10:00Z')
        a=dict(id=AUTOMATION,is_enabled=True,schedule='BEGIN:VEVENT\nDTSTART:20261102T220500Z\nRRULE:FREQ=HOURLY\nEND:VEVENT',run_details={'last_run':run})
        receipt=dict(run_id='run',trigger='schedule',status='complete',scheduled_for=run['scheduled_for'],completed_at='2026-11-02T22:09:00Z',completed_actions=['lifecycle checkpoint'],receipt_path='config/content_review_run_receipts/run.json')
        self.assertTrue(verified_completion(a,receipt)['evidence_verified'])
        local={**a,'schedule':'BEGIN:VEVENT\nDTSTART;TZID=America/Toronto:20261102T170500\nRRULE:FREQ=HOURLY\nEND:VEVENT'}
        self.assertTrue(verified_completion(local,receipt)['evidence_verified'])
        self.assertEqual(expected_next(local),'2026-11-02T23:05:00+00:00')
        self.assertEqual(expected_next({**local,'run_details':{}}),'2026-11-02T22:05:00+00:00')
        self.assertIsNone(expected_next({**local,'is_enabled':False}))
        for change in ({'trigger':'manual'},{'run_id':'other'},{'completed_actions':[]},{'scheduled_for':'2026-11-02T22:06:00Z'},{'completed_at':'2026-11-02T22:20:00Z'}):
            self.assertIsNone(verified_completion(a,{**receipt,**change}))
        self.assertIsNone(verified_completion(a,None))
        run['recorded_status']='in_progress';self.assertIsNone(verified_completion(a,receipt))
        self.assertEqual(find_automation({'structuredContent':{'automations':[a]}})['id'],AUTOMATION)

    def test_start_heartbeat_and_completion_preserve_real_native_state(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td);(root/'config').mkdir()
            original={'lease':{'run_id':'run','expires_at':'2026-11-02T23:20:00Z'},'ready_total':7}
            (root/'config/content_review_worker_status.json').write_text(json.dumps(original))
            native={'id':AUTOMATION,'is_enabled':True,'schedule':'BEGIN:VEVENT\nDTSTART:20261102T224500Z\nRRULE:FREQ=HOURLY\nEND:VEVENT',
                'run_details':{'last_run':{'id':'run','recorded_status':'in_progress','started_at':'2026-11-02T22:49:00Z','scheduled_for':'2026-11-02T22:45:00Z'}}}
            state,data=runtime_checkpoint(root,native,'run','start','2026-11-02T22:50:00Z')
            self.assertEqual(state['last_started_at'],'2026-11-02T22:49:00Z')
            self.assertEqual(state['current_run']['application_status'],'running')
            self.assertEqual(state['ready_total'],7);self.assertEqual(state['lease'],original['lease'])
            save_runtime(root,state,data)
            state,data=runtime_checkpoint(root,native,'run','complete','2026-11-02T22:56:00Z')
            self.assertEqual(state['current_run']['application_status'],'complete')
            self.assertEqual(data['scheduler']['last_run']['recorded_status'],'in_progress')
            self.assertIsNone(data['scheduler']['last_verified_scheduled_success'])
            save_runtime(root,state,data)
            with self.assertRaises(ValueError):runtime_checkpoint(root,native,'run','running','2026-11-02T22:57:00Z')
            for owner,at in [('other','2026-11-02T22:57:00Z'),('run','2026-11-02T23:21:00Z')]:
                with self.assertRaises(ValueError):runtime_checkpoint(root,native,owner,'start',at)

if __name__=='__main__':unittest.main()


def test_verified_owner_pause_skips_only_intentionally_suspended_slots():
    a={'id':AUTOMATION,'is_enabled':True,'schedule':'BEGIN:VEVENT\nDTSTART:20261105T164500Z\nRRULE:FREQ=HOURLY\nEND:VEVENT',
       'run_details':{'last_run':{'scheduled_for':'2026-11-05T16:45:00Z'}}}
    pause={'automation_id':AUTOMATION,'paused_at':'2026-11-05T16:55:52Z','resumed_at':'2026-11-05T17:58:09Z',
           'owner_authorized':True,'pause_readback_verified':True,'resume_readback_verified':True}
    assert expected_next(a,[pause])=='2026-11-05T18:45:00+00:00'
    later={**pause,'paused_at':'2026-11-05T18:08:44Z','resumed_at':'2026-11-05T19:00:00Z'}
    assert expected_next(a,[pause,later])=='2026-11-05T19:45:00+00:00'
    assert expected_next(a,[later])=='2026-11-05T17:45:00+00:00' # Genuine earlier miss remains visible.
    assert expected_next(a,[{**pause,'resume_readback_verified':False}])=='2026-11-05T17:45:00+00:00'
    assert expected_next(a,[{**pause,'automation_id':'other'}])=='2026-11-05T17:45:00+00:00'
    assert expected_next({**a,'is_enabled':False},[pause]) is None

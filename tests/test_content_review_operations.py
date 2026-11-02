import unittest
from tools.content_review.operations import verified_completion,find_automation,AUTOMATION

class OperationsTests(unittest.TestCase):
    def test_completion_requires_native_terminal_schedule_and_matching_real_receipt(self):
        run=dict(id='run',recorded_status='completed',scheduled_for='2026-11-02T22:05:00Z',started_at='2026-11-02T22:05:02Z',completed_at='2026-11-02T22:10:00Z')
        a=dict(id=AUTOMATION,is_enabled=True,schedule='BEGIN:VEVENT\nDTSTART:20261102T220500Z\nRRULE:FREQ=HOURLY\nEND:VEVENT',run_details={'last_run':run})
        receipt=dict(run_id='run',trigger='schedule',status='complete',scheduled_for=run['scheduled_for'],completed_at='2026-11-02T22:09:00Z',completed_actions=['lifecycle checkpoint'],receipt_path='config/content_review_run_receipts/run.json')
        self.assertTrue(verified_completion(a,receipt)['evidence_verified'])
        for change in ({'trigger':'manual'},{'run_id':'other'},{'completed_actions':[]},{'scheduled_for':'2026-11-02T22:06:00Z'},{'completed_at':'2026-11-02T22:20:00Z'}):
            self.assertIsNone(verified_completion(a,{**receipt,**change}))
        self.assertIsNone(verified_completion(a,None))
        run['recorded_status']='in_progress';self.assertIsNone(verified_completion(a,receipt))
        self.assertEqual(find_automation({'structuredContent':{'automations':[a]}})['id'],AUTOMATION)

if __name__=='__main__':unittest.main()

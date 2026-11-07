import copy,hashlib,unittest
from datetime import datetime,timezone,timedelta
from tools.content_review.snapshot_integrity import verify_bytes
from tools.content_review.provider_policy import resolve
from tools.content_review.manifest_integrity import parse
from tools.content_review.lifecycle import evaluate
class RecoveryIntegrity(unittest.TestCase):
 def test_valid_json_subset_is_not_complete_blob(self):
  whole=b'{"records":[{"candidate_id":"a"},{"candidate_id":"b"}]}';sha=hashlib.sha1(b'blob '+str(len(whole)).encode()+b'\0'+whole).hexdigest()
  self.assertEqual(verify_bytes(whole,sha,len(whole))['size'],len(whole))
  with self.assertRaises(ValueError):verify_bytes(b'{"records":[]}',sha,len(whole))
 def test_unicode_bytes_not_character_count(self):
  body='é'.encode();sha=hashlib.sha1(b'blob 2\0'+body).hexdigest();verify_bytes(body,sha,2)
  with self.assertRaises(ValueError):verify_bytes(body,sha,1)
 def test_truncation_marker_inside_valid_json(self):
  with self.assertRaises(ValueError):parse('{"records":[{"candidate_id":"a","title":"[truncated]"}]}')
 def test_longest_deadline_survives_review_resumption(self):
  now=datetime.now(timezone.utc);later=now+timedelta(hours=5)
  p=resolve({'requests_enabled':True,'retry_not_before':later.isoformat()},{},{'providers':[{'id':'openalex','owner_hold_until':None}]},now)
  self.assertFalse(p['allowed']);self.assertEqual(p['retry_not_before'],later.isoformat())
 def test_verified_candidate_label_is_not_missing_export_support(self):
  r={'candidate_id':'a','content_sha256':'h','document_type':'research_paper_candidate','verified_document_type':'research_paper','preflight':{'checks':{'format':{'status':'passed','content_sha256':'h','checked_at':'2026-11-04T00:00:00Z','evidence':'actual paper'}}}}
  e=evaluate(r);self.assertNotEqual(e['state'],'awaiting_software_support');self.assertEqual(e['initial_check_status'],'partially_checked')
 def test_unreconciled_provider_hold_does_not_expire_with_local_minimum(self):
  p=resolve({'requests_enabled':False,'retry_not_before':'2020-01-01T00:00:00Z',
             'reconciliation_hold':{'http_status':429}}, {}, {}, datetime.now(timezone.utc))
  self.assertFalse(p['allowed']);self.assertEqual(p['request_limit'],0)
  self.assertIn('reconciliation',p['reason'])
 def test_missing_enablement_or_uncleared_hold_never_allows_a_request(self):
  for policy in ({},{'requests_enabled':True,'reconciliation_hold':{'http_status':429}},
                 {'requests_enabled':True,'reconciliation_hold':{}},
                 {'requests_enabled':True,'owner_pause':{'automatic_release':False}}):
   result=resolve(policy,{}, {},datetime.now(timezone.utc)+timedelta(days=30))
   self.assertFalse(result['allowed']);self.assertEqual(result['request_limit'],0)
if __name__=='__main__':unittest.main()

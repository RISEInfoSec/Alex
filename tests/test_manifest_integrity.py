import json
import unittest
from tools.content_review.manifest_integrity import parse,validate_update

class ManifestIntegrityTests(unittest.TestCase):
    def test_invalid_or_truncated_json_is_rejected(self):
        for value in ('{"records":[ ... content truncated ... ]}', '{}...truncated', '[]'):
            with self.assertRaises((ValueError,TypeError)):parse(value)
    def test_identity_content_and_decision_preservation(self):
        r={'candidate_id':'one','content_sha256':'a','decision':'approved'}
        old=json.dumps({'records':[r]})
        for new in ({'records':[]},{'records':[{**r,'content_sha256':'b'}]},{'records':[{**r,'decision':'pending'}]},{'records':[r,r]}):
            with self.assertRaises(ValueError):validate_update(old,json.dumps(new))
        moved=json.dumps({'records':[],'preflight_records':[r,{'candidate_id':'two'}]})
        self.assertEqual(validate_update(old,moved)['preserved_identities'],1)
        changed=json.dumps({'records':[{**r,'content_sha256':'b'}]})
        self.assertEqual(validate_update(old,changed,allowed_content_changes=['one'])['new_count'],1)

if __name__=='__main__':unittest.main()

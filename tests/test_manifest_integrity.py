import json
import unittest
from tools.content_review.manifest_integrity import parse,validate_update,validate_hashes,reviewed_digest

class ManifestIntegrityTests(unittest.TestCase):
    def test_type_change_requires_explicit_new_hash_and_retained_version(self):
        r=dict(candidate_id='one',document_type='research_paper_candidate',decision='pending')
        r['content_sha256']=reviewed_digest(r)
        n={**r,'document_type':'research_paper'}
        with self.assertRaises(ValueError):validate_hashes({'records':[n]})
        n['content_sha256']=reviewed_digest(n)
        with self.assertRaises(ValueError):validate_update(json.dumps({'records':[r]}),json.dumps({'records':[n]}))
        n['reviewed_content_versions']=[dict(content_sha256=r['content_sha256'],record=r,reason='Verified actual paper type; exact prior version retained.')]
        validate_update(json.dumps({'records':[r]}),json.dumps({'records':[n]}))
        validate_hashes({'records':[n]})
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

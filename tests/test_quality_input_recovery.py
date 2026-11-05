import copy
import pytest
from tools.content_review.quality_inputs import restore_affiliations
from tools.content_review.paid_worker import digest, reviewed_digest
from alex.pipelines.apwg_quality_review import assess


def test_original_affiliation_restores_existing_score_without_changing_review_identity():
    upstream = dict(candidate_id='original', affiliations='University of Jeddah; Air University')
    row = dict(candidate_id='weekly-test', upstream_candidate_id='original',
               source_record_sha256=digest(upstream), title='Cybercrime phishing detection',
               abstract='A study of cybercrime and phishing detection using reproducible methods.',
               authors='Test Author', venue='Scientific Reports', year=2026,
               doi='10.example/test', source_url='https://example.org/paper',
               document_type='research_paper', decision='pending', citation_count=None)
    row['content_sha256'] = reviewed_digest(row)
    proof = dict(receipt='test-only', body_sha256='1'*64, inspection='Synthetic test fixture')
    before = copy.deepcopy(row)
    fixed = restore_affiliations(row, upstream, source_proof=proof, checked_at='2026-11-05T00:00:00Z')
    assert assess(fixed)['quality_institution_bonus'] == 10
    assert assess(row)['quality_institution_bonus'] == 0
    assert reviewed_digest(fixed) == row['content_sha256']
    assert fixed['decision'] == 'pending' and row == before
    assert restore_affiliations(fixed, upstream, source_proof=proof, checked_at='later') == fixed
    for defect in ('fingerprint','decision','content','conflict','evidence'):
        changed=copy.deepcopy(row); p=copy.deepcopy(proof)
        if defect=='fingerprint':changed['source_record_sha256']='0'*64
        if defect=='decision':changed['decision']='approved'
        if defect=='content':changed['title']='Changed'
        if defect=='conflict':changed['affiliations']='Conflicting university'
        if defect=='evidence':p.pop('body_sha256')
        with pytest.raises(ValueError):
            restore_affiliations(changed, upstream, source_proof=p, checked_at='now')

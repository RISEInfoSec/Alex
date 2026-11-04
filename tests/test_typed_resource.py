import pytest
from tools.content_review.typed_resource import validate_staging

def test_typed_staging_cannot_grant_paper_or_public_status():
    s=dict(actual_type='best_practice_guide',content_sha256='h',source_sha256='a'*64,text_sha256='b'*64,source_receipt='receipt',author='Group',publication_date='2026-09',publication_version='2.0',publication_ready=False)
    r=dict(content_sha256='h',verified_document_type='best_practice_guide',typed_resource_staging=s,review_ready=False)
    assert validate_staging(r)==s
    r['review_ready']=True
    with pytest.raises(ValueError,match='admission'):validate_staging(r)
    r['review_ready']=False;s['actual_type']='research_paper'
    with pytest.raises(ValueError,match='type'):validate_staging(r)

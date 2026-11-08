from tests.test_content_review_source_pending import fixture
from tools.content_review.source_reservation_identity import find


def test_reservation_identity_comes_from_exact_immutable_addition(tmp_path):
    _,review,_,_,_,_,reservation,_=fixture(tmp_path)
    result=find(tmp_path,review)
    assert result['reservation_head']==reservation and len(result['request_id'])==64

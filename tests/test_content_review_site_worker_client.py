import io
import json
import urllib.error

import pytest

from tools.content_review.site_worker_client import ORIGIN, post


class Response:
    def __init__(self, value, status=200):
        self.raw = json.dumps(value).encode();self.status = status
    def read(self, amount): return self.raw[:amount]
    def __enter__(self): return self
    def __exit__(self, *_): pass


class Opener:
    def __init__(self, response): self.response=response;self.requests=[]
    def open(self, request, timeout):
        self.requests.append((request, timeout))
        if isinstance(self.response, BaseException): raise self.response
        return self.response


def test_client_targets_only_the_private_site_and_redacts_the_token():
    opener=Opener(Response({'status':'committed_and_read_back','commit_sha':'a'*40,'owner':'private-value'}))
    result=post('lease',{'proposal':{}},'secret-value',opener=opener)
    request,timeout=opener.requests[0]
    assert request.full_url==ORIGIN+'/api/content-review-lease' and timeout==45
    assert request.get_header('Oai-sites-authorization')=='Bearer secret-value'
    assert result['commit_sha']=='a'*40 and result['native_observation_authenticated'] is False
    assert 'secret-value' not in json.dumps(result) and 'private-value' not in json.dumps(result)


def test_timeout_unknown_response_and_unconfirmed_write_require_reconciliation():
    for response in [TimeoutError(),Response({'status':'unexpected'}),
        Response({'status':'blocked','reason':'commit_unconfirmed_reconcile_fence'},409),
        Response({'status':'blocked','reason':'unrecognized'},409)]:
        result=post('soups_intake',{},'secret-value',opener=Opener(response))
        assert result['status']=='outcome_unknown' and result['reconcile_before_retry'] is True


def test_explicit_rejection_is_blocked_and_never_claims_processing():
    result=post('soups_intake',{},'secret-value',opener=Opener(Response({'status':'blocked','reason':'worker_not_verified'},409)))
    assert result['status']=='blocked' and result['reconcile_before_retry'] is False
    receipt='config/content_review_intake_receipts/'+'b'*64+'.json'
    ok={'status':'committed_and_read_back','commit_sha':'a'*40,'candidate_count':5,'receipt_path':receipt,
        'candidate_processing':False,'publication_verified':False}
    result=post('soups_intake',{},'secret-value',opener=Opener(Response(ok)))
    assert result['candidate_processing'] is False and result['publication_verified'] is False


def test_request_rejects_bad_action_or_invalid_token_before_network():
    opener=Opener(Response({}))
    for action,token in [('wrong','secret'),('lease','bad\nsecret')]:
        with pytest.raises(ValueError):post(action,{},token,opener=opener)
    assert opener.requests==[]

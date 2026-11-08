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
        Response({'status':'blocked','reason':'heartbeat_unconfirmed_reconcile_ref'},409),
        Response({'status':'blocked','reason':'unrecognized'},409)]:
        result=post('soups_intake',{},'secret-value',opener=Opener(response))
        assert result['status']=='outcome_unknown' and result['reconcile_before_retry'] is True


def test_long_duplicate_timeout_remains_bounded_and_never_retries():
    opener=Opener(TimeoutError())
    result=post('duplicate',{},'secret-value',opener=opener)
    assert len(opener.requests)==1 and opener.requests[0][1]==180
    assert result['status']=='outcome_unknown' and result['reconcile_before_retry'] is True


def test_explicit_rejection_is_blocked_and_never_claims_processing():
    result=post('soups_intake',{},'secret-value',opener=Opener(Response({'status':'blocked','reason':'worker_not_verified'},409)))
    assert result['status']=='blocked' and result['reconcile_before_retry'] is False
    receipt='config/content_review_intake_receipts/'+'b'*64+'.json'
    ok={'status':'committed_and_read_back','commit_sha':'a'*40,'candidate_count':5,'receipt_path':receipt,
        'candidate_processing':False,'publication_verified':False}
    result=post('soups_intake',{},'secret-value',opener=Opener(Response(ok)))
    assert result['candidate_processing'] is False and result['publication_verified'] is False


def test_no_work_receipt_never_claims_native_success_or_candidate_processing():
    response={'status':'committed_and_read_back','commit_sha':'a'*40,'receipt_path':'config/content_review_run_receipts/run.json',
              'candidate_processing':False,'native_completion_verified':False,'publication_verified':False}
    result=post('no_work',{},'secret-value',opener=Opener(Response(response)))
    assert result['candidate_processing'] is False and result['native_completion_verified'] is False
    response['native_completion_verified']=True
    assert post('no_work',{},'secret-value',opener=Opener(Response(response)))['status']=='outcome_unknown'


def test_duplicate_checkpoint_reports_only_a_confirmed_mechanical_gate():
    receipt='config/content_review_mechanical_checkpoints/'+'b'*64+'.json'
    response={'status':'committed_and_read_back','commit_sha':'a'*40,'receipt_path':receipt,'gate':'duplicates',
              'candidate_processing':True,'native_completion_verified':False,'publication_verified':False}
    opener=Opener(Response(response));result=post('duplicate',{},'secret-value',opener=opener)
    assert opener.requests[0][0].full_url==ORIGIN+'/api/content-review-duplicate'
    assert opener.requests[0][1]==180 and result['gate']=='duplicates' and result['candidate_processing'] is True
    assert result['native_completion_verified'] is False and result['publication_verified'] is False
    response['publication_verified']=True
    assert post('duplicate',{},'secret-value',opener=Opener(Response(response)))['status']=='outcome_unknown'


def test_source_gate_requires_confirmed_receipt_and_never_claims_publication():
    receipt='config/content_review_source_gate_checkpoints/'+'b'*64+'.json'
    response={'status':'committed_and_read_back','commit_sha':'a'*40,'receipt_path':receipt,'gate':'access',
              'candidate_processing':True,'native_completion_verified':False,'publication_verified':False}
    opener=Opener(Response(response));result=post('source_gate',{},'secret-value',opener=opener)
    assert opener.requests[0][0].full_url==ORIGIN+'/api/content-review-source-gate' and opener.requests[0][1]==180
    assert result['gate']=='access' and result['candidate_processing'] is True and result['publication_verified'] is False
    response['gate']='quality'
    assert post('source_gate',{},'secret-value',opener=Opener(Response(response)))['status']=='outcome_unknown'


def test_completed_run_receipt_does_not_claim_native_or_publication_success():
    response={'status':'committed_and_read_back','commit_sha':'a'*40,'receipt_path':'config/content_review_run_receipts/run.json',
              'candidate_processing':True,'native_completion_verified':False,'publication_verified':False}
    opener=Opener(Response(response));result=post('completion',{},'secret-value',opener=opener)
    assert opener.requests[0][0].full_url==ORIGIN+'/api/content-review-completion' and opener.requests[0][1]==180
    assert result['candidate_processing'] is True and result['native_completion_verified'] is False
    response['native_completion_verified']=True
    assert post('completion',{},'secret-value',opener=Opener(Response(response)))['status']=='outcome_unknown'


def test_source_gate_completion_uses_bounded_private_route_and_truthful_receipt():
    response={'status':'committed_and_read_back','commit_sha':'a'*40,'receipt_path':'config/content_review_run_receipts/run.json',
              'candidate_processing':True,'native_completion_verified':False,'publication_verified':False}
    opener=Opener(Response(response));result=post('source_gate_completion',{},'secret-value',opener=opener)
    assert opener.requests[0][0].full_url==ORIGIN+'/api/content-review-source-gate-completion' and opener.requests[0][1]==180
    assert result['candidate_processing'] is True and result['native_completion_verified'] is False


def test_source_reservation_does_not_claim_the_workflow_ran():
    response={'status':'committed_and_read_back','commit_sha':'a'*40,'request_path':'config/content_review_source_requests/'+'b'*64+'.json',
              'source_request_limit':30,'source_request_reserved':True,'source_workflow_verified':False,
              'candidate_processing':False,'publication_verified':False}
    opener=Opener(Response(response));result=post('source_request',{},'secret-value',opener=opener)
    assert opener.requests[0][0].full_url==ORIGIN+'/api/content-review-source-request'
    assert result['source_request_reserved'] is True and result['source_workflow_verified'] is False and result['candidate_processing'] is False
    response['source_workflow_verified']=True
    assert post('source_request',{},'secret-value',opener=Opener(Response(response)))['status']=='outcome_unknown'


def test_source_result_accounts_verified_workflow_without_claiming_a_gate_pass():
    response={'status':'committed_and_read_back','commit_sha':'a'*40,'receipt_path':'config/content_review_source_receipts/'+'b'*64+'.json',
              'source_requests':3,'source_workflow_verified':True,'candidate_processing':False,'publication_verified':False}
    opener=Opener(Response(response));result=post('source_result',{},'secret-value',opener=opener)
    assert opener.requests[0][0].full_url==ORIGIN+'/api/content-review-source-result' and opener.requests[0][1]==180
    assert result['source_requests']==3 and result['source_workflow_verified'] is True and result['candidate_processing'] is False
    response['candidate_processing']=True
    assert post('source_result',{},'secret-value',opener=Opener(Response(response)))['status']=='outcome_unknown'


def test_request_rejects_bad_action_or_invalid_token_before_network():
    opener=Opener(Response({}))
    for action,token in [('wrong','secret'),('lease','bad\nsecret')]:
        with pytest.raises(ValueError):post(action,{},token,opener=opener)
    assert opener.requests==[]


def test_source_retention_reports_evidence_without_claiming_a_gate():
    response={'status':'committed_and_read_back','commit_sha':'a'*40,'receipt_path':'config/content_review_source_checkpoints/'+'b'*64+'.json',
              'gate_passed':False,'candidate_processing':False,'publication_verified':False}
    opener=Opener(Response(response));result=post('source_retention',{},'secret-value',opener=opener)
    assert opener.requests[0][0].full_url==ORIGIN+'/api/content-review-source-retention' and opener.requests[0][1]==180
    assert result['gate_passed'] is False and result['candidate_processing'] is False
    response['gate_passed']=True
    assert post('source_retention',{},'secret-value',opener=Opener(Response(response)))['status']=='outcome_unknown'


def test_source_completion_does_not_claim_candidate_or_native_completion():
    response={'status':'committed_and_read_back','commit_sha':'a'*40,'receipt_path':'config/content_review_run_receipts/run.json',
              'source_requests':3,'source_workflow_verified':True,'candidate_processing':False,'native_completion_verified':False,'publication_verified':False}
    opener=Opener(Response(response));result=post('source_completion',{},'secret',opener=opener)
    assert opener.requests[0][0].full_url==ORIGIN+'/api/content-review-source-completion'
    assert result['source_requests']==3 and result['candidate_processing'] is False and result['native_completion_verified'] is False
    response['candidate_processing']=True
    assert post('source_completion',{},'secret',opener=Opener(Response(response)))['status']=='outcome_unknown'


def test_pending_source_release_preserves_deferred_status_without_claiming_work():
    response={'status':'committed_and_read_back','commit_sha':'a'*40,'receipt_path':'config/content_review_run_receipts/run.json',
              'source_status':'source_run_pending','candidate_processing':False,'native_completion_verified':False,'publication_verified':False}
    opener=Opener(Response(response));result=post('source_pending',{},'secret',opener=opener)
    assert opener.requests[0][0].full_url==ORIGIN+'/api/content-review-source-pending'
    assert result['source_status']=='source_run_pending' and result['candidate_processing'] is False and result['native_completion_verified'] is False
    response['source_status']='source_artifact_ready'
    assert post('source_pending',{},'secret',opener=Opener(Response(response)))['status']=='outcome_unknown'

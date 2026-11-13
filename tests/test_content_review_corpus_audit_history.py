from copy import deepcopy
import hashlib
import json

import pytest

from tests.test_content_review_corpus_audit_adapter import fixture as data_fixture
from tests.test_content_review_verified_inputs import git, put
from tools.content_review.corpus_audit_history import plan, RELEASE


def fixture(repo):
    snapshot, manifests, public = data_fixture()
    decision=snapshot['decisions'][0];submission=snapshot['submissions'][0];row=manifests['corpus-audit']['records'][0]
    historic={'candidate_id':decision['candidate_id'],'decision':decision['decision'],'submission_id':decision['submission_id'],
              'revision':decision['revision'],'reviewed_content_sha256':decision['content_sha256'],
              'payload_hash':submission['payload_hash'],'public_record_sha256':row['original_record_sha256'],
              'original_public_id':row['original_public_id']}
    removals=[historic];keeps=[]
    digest=hashlib.sha256(json.dumps({'removals':removals,'keeps':keeps},sort_keys=True,ensure_ascii=False).encode()).hexdigest()
    receipt={'release_id':RELEASE,'records_sha256':digest,'removals':removals,'keeps':keeps,'removed':1,'audit_kept':0,'records_after':0}
    request={'release_id':RELEASE,'publication_approved':True,'records_sha256':digest,'removals':removals,'keeps':keeps}
    git(repo,'init','--quiet');put(repo,'README','initial');git(repo,'add','.');git(repo,'commit','-qm','initial')
    ancestor=git(repo,'rev-parse','HEAD')
    put(repo,'config/content_review_releases/'+RELEASE+'.json',request)
    put(repo,'data/content_review_release_receipts/'+RELEASE+'.json',receipt)
    put(repo,'data/papers.json',[]);git(repo,'add','.');git(repo,'commit','-qm','historical publication')
    main=git(repo,'rev-parse','HEAD')
    application={'schema_version':1,'release_id':RELEASE,'status':'published_live_verified','public_commit':main,
       'publication_receipt':'config/content_review_publication_receipts/'+RELEASE+'.json',
       'audit_removals':1,'audit_keeps':0,'completed_job_ids':['job'],
       'live_verification':{'live_records':0,'public_sha256':hashlib.sha256(b'[]').hexdigest()}}
    put(repo,application['publication_receipt'],receipt);put(repo,'config/review_application_status.json',application)
    git(repo,'add','.');git(repo,'commit','-qm','record historical review application')
    review=git(repo,'rev-parse','HEAD')
    return snapshot,manifests,public,review,main,ancestor,application


def call(repo,snapshot,manifests,public,review,main):
    return plan(repo,review,main,snapshot,deepcopy(snapshot),manifests,public,
                observed_heads={'review':review,'main':main})


def test_receipt_bound_historical_removal_is_not_replayed_or_claimed_current(tmp_path):
    snap,manifests,public,review,main,_,_=fixture(tmp_path)
    public[0]['title']='Changed since original audit'
    before=deepcopy((snap,manifests,public))
    result=call(tmp_path,snap,manifests,public,review,main)
    assert result['outcome_counts']=={'historical_removal_receipted':1}
    assert result['outcomes'][0]['current_publication_verified'] is False
    assert result['publication_authorized'] is False and result['writes']==0
    assert 'private-user' not in json.dumps(result)
    assert (snap,manifests,public)==before


def test_missing_historical_job_never_becomes_receipted(tmp_path):
    snap,manifests,public,review,main,_,app=fixture(tmp_path)
    app['completed_job_ids']=['different-job'];put(tmp_path,'config/review_application_status.json',app)
    git(tmp_path,'add','.');git(tmp_path,'commit','-qm','different completed job');review=git(tmp_path,'rev-parse','HEAD')
    result=call(tmp_path,snap,manifests,public,review,main)
    assert result['outcomes'][0]['status']=='removal_review_requested'
    assert result['publication_authorized'] is False


def test_changed_receipt_or_unrelated_main_fails_closed(tmp_path):
    snap,manifests,public,review,main,ancestor,app=fixture(tmp_path)
    with pytest.raises(ValueError,match='not in current main history'):
        call(tmp_path,snap,manifests,public,review,ancestor)
    path=tmp_path/app['publication_receipt'];receipt=json.loads(path.read_text());receipt['records_sha256']='0'*64
    put(tmp_path,app['publication_receipt'],receipt);git(tmp_path,'add','.');git(tmp_path,'commit','-qm','changed receipt')
    with pytest.raises(ValueError,match='evidence differs'):
        call(tmp_path,snap,manifests,public,git(tmp_path,'rev-parse','HEAD'),main)


def test_changed_reviewed_candidate_cannot_reuse_old_receipt(tmp_path):
    snap,manifests,public,review,main,_,_=fixture(tmp_path)
    manifests['corpus-audit']['records'][0]['title']='Modified content with old stored hash'
    result=call(tmp_path,snap,manifests,public,review,main)
    assert result['outcomes'][0]['status']=='held'
    assert result['outcomes'][0]['reason']=='reviewed_content_hash_mismatch'

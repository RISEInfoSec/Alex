from datetime import timedelta
import json

import pytest

from tests.test_content_review_monitor_snapshot import fixture as native_fixture
from tests.test_content_review_verified_inputs import git, put
from tools.content_review.detached_monitor import prepare


def fixture(repo):
    now,config,worker,observer,receipt=native_fixture()
    git(repo,'init','--quiet')
    put(repo,'config/content_review_monitor_config.json',config)
    put(repo,'config/content_review_worker_status.json',{'current_run':{'observed_at':now.isoformat()}})
    put(repo,receipt['receipt_path'],receipt)
    git(repo,'add','.');git(repo,'commit','-qm','review')
    review=git(repo,'rev-parse','HEAD');branch=git(repo,'symbolic-ref','--short','HEAD')
    return now,review,branch,worker,observer


def call(repo,now,review,monitor,worker,observer):
    return prepare(repo,review,monitor,worker,observer,observed_heads={'review':review,'monitor':monitor},at=now)


def test_observer_prepares_separate_ref_with_hash_bound_worker_and_receipt(tmp_path):
    now,review,branch,worker,observer=fixture(tmp_path)
    proposal=call(tmp_path,now,review,review,worker,observer)
    record=json.loads(proposal['content'])
    assert proposal['writes']==0 and proposal['base_blob'] is None
    assert record['source_review_commit']==review and record['source_receipt_blob_sha']
    assert record['receipt_check']['verified'] is True and record['observer']['native_status']=='in_progress'
    git(tmp_path,'checkout','-qb','monitor');put(tmp_path,proposal['path'],proposal['content'])
    git(tmp_path,'add','.');git(tmp_path,'commit','-qm','monitor')
    monitor=git(tmp_path,'rev-parse','HEAD');git(tmp_path,'checkout','-q',branch)
    newer=call(tmp_path,now+timedelta(seconds=1),review,monitor,worker,observer)
    assert newer['base_blob']['commit']==monitor
    assert json.loads(newer['content'])['previous_monitor_blob_sha']==proposal['blob_sha']
    assert git(tmp_path,'rev-parse','HEAD')==review


def test_changed_head_or_unverified_observer_blocks_monitor(tmp_path):
    now,review,_,worker,observer=fixture(tmp_path)
    with pytest.raises(ValueError,match='Current review and monitor heads'):
        prepare(tmp_path,review,review,worker,observer,observed_heads={'review':'f'*40,'monitor':review},at=now)
    observer['run_details']['last_run']['recorded_status']='completed'
    with pytest.raises(ValueError,match='observer run is not verified'):
        call(tmp_path,now,review,review,worker,observer)

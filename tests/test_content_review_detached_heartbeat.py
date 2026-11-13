from datetime import timedelta
import json

import pytest

from tests.test_content_review_heartbeat_evidence import fixture as state_fixture
from tests.test_content_review_verified_inputs import git,put
from tools.content_review.detached_heartbeat import prepare


def fixture(repo):
    now,_,state=state_fixture();git(repo,'init','--quiet')
    put(repo,'config/content_review_worker_status.json',state)
    put(repo,'config/content_review_monitor_config.json',{'target_automation_id':'Automation_worker'})
    git(repo,'add','.');git(repo,'commit','-qm','review')
    review=git(repo,'rev-parse','HEAD');branch=git(repo,'symbolic-ref','--short','HEAD')
    return now,review,branch


def test_prepares_independent_ref_without_modifying_review_head(tmp_path):
    now,review,branch=fixture(tmp_path)
    proposal=prepare(tmp_path,review,review,'worker','run',at=now+timedelta(seconds=5))
    assert proposal['writes']==0 and proposal['base_blob'] is None
    assert json.loads(proposal['content'])['review_head']==review
    git(tmp_path,'checkout','-qb','heartbeat')
    put(tmp_path,proposal['path'],proposal['content']);git(tmp_path,'add','.');git(tmp_path,'commit','-qm','heartbeat')
    hb=git(tmp_path,'rev-parse','HEAD');git(tmp_path,'checkout','-q',branch)
    newer=prepare(tmp_path,review,hb,'worker','run',at=now+timedelta(seconds=30))
    assert newer['base_blob']['commit']==hb and newer['review_head']==review
    assert git(tmp_path,'rev-parse','HEAD')==review
    with pytest.raises(ValueError,match='backwards'):
        prepare(tmp_path,review,hb,'worker','run',at=now+timedelta(seconds=4))


def test_wrong_owner_or_unverified_head_is_rejected(tmp_path):
    now,review,_=fixture(tmp_path)
    with pytest.raises(ValueError):prepare(tmp_path,review,review,'other','run',at=now)
    with pytest.raises(ValueError):prepare(tmp_path,review,'bad','worker','run',at=now)

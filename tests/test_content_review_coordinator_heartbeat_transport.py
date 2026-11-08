from datetime import timedelta
import errno
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest

from tests.test_content_review_detached_heartbeat import fixture
from tests.test_content_review_verified_inputs import git,put
from tools.content_review.coordinator_heartbeat_transport import DetachedHeartbeatPulse,REVIEW,MAIN,HEARTBEAT


def test_site_heartbeat_is_bound_to_current_heads_and_read_back(tmp_path):
    now,review,branch=fixture(tmp_path);heads={REVIEW:review,MAIN:review,HEARTBEAT:review};sent=[]
    def read(_):return dict(heads)
    def fetch(_repo,_heads,_run):pass
    def send(action,payload,token):
        assert action=='heartbeat' and token=='private-test-token';sent.append(payload)
        git(tmp_path,'checkout','-qb','heartbeat');put(tmp_path,payload['proposal']['path'],payload['proposal']['content'])
        git(tmp_path,'add','.');git(tmp_path,'commit','-qm','beat');heads[HEARTBEAT]=git(tmp_path,'rev-parse','HEAD')
        git(tmp_path,'checkout','-q',branch)
        return {'status':'committed_and_read_back','commit_sha':heads[HEARTBEAT]}
    pulse=DetachedHeartbeatPulse(tmp_path,'private-test-token',review,review,'worker','run',heads=read,fetch=fetch,send=send,
                                 clock=lambda:now+timedelta(seconds=5))
    result=pulse()
    assert result=={'status':'committed_and_read_back','commit_sha':heads[HEARTBEAT]}
    assert 'private-test-token' not in json.dumps(result) and len(sent)==1
    assert git(tmp_path,'rev-parse','HEAD')==review


def test_moved_head_or_ambiguous_write_stops_without_a_retry(tmp_path):
    now,review,_=fixture(tmp_path);heads={REVIEW:review,MAIN:review,HEARTBEAT:review};calls=[]
    def read(_):return dict(heads)
    def send(*args):calls.append(1);return {'status':'outcome_unknown'}
    pulse=DetachedHeartbeatPulse(tmp_path,'secret',review,review,'worker','run',heads=read,fetch=lambda *args:None,send=send,clock=lambda:now)
    heads[MAIN]='a'*40
    with pytest.raises(ValueError,match='heads changed'):pulse()
    assert calls==[]
    heads[MAIN]=review
    with pytest.raises(ValueError,match='unconfirmed'):pulse()
    assert len(calls)==1


def test_fetches_observed_commits_when_heartbeat_moves_and_calls_overlap(tmp_path,monkeypatch):
    from tools.content_review import coordinator_heartbeat_transport as transport
    remote=tmp_path/'remote.git';source=tmp_path/'source';checkout=tmp_path/'checkout'
    subprocess.run(['git','init','--bare','-q',str(remote)],check=True)
    subprocess.run(['git','init','-q',str(source)],check=True)
    put(source,'data.txt','one');git(source,'add','.');git(source,'commit','-qm','one')
    first=git(source,'rev-parse','HEAD')
    git(source,'remote','add','origin',str(remote))
    for ref in (REVIEW,MAIN,HEARTBEAT):git(source,'push','-q','origin','HEAD:'+ref)
    subprocess.run(['git','clone','-q','--no-checkout',str(remote),str(checkout)],check=True)
    put(source,'data.txt','two');git(source,'add','.');git(source,'commit','-qm','two')
    second=git(source,'rev-parse','HEAD');git(source,'push','-q','origin','HEAD:'+HEARTBEAT)
    old={REVIEW:first,MAIN:first,HEARTBEAT:first};new={REVIEW:first,MAIN:first,HEARTBEAT:second}
    monkeypatch.setattr(transport,'_check_remote',lambda repo:None)
    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(lambda observed:transport.fetch_heads(checkout,observed,'run'),[old,new]))
    assert git(checkout,'cat-file','-t',first)=='commit'
    assert git(checkout,'cat-file','-t',second)=='commit'
    assert git(checkout,'for-each-ref','--format=%(refname)','refs/codex/content-review/')==''


def test_fetch_rejects_unverified_object_identity(tmp_path,monkeypatch):
    from tools.content_review import coordinator_heartbeat_transport as transport
    monkeypatch.setattr(transport,'_check_remote',lambda repo:pytest.fail('No Git access expected'))
    with pytest.raises(ValueError,match='Invalid coordinator fetch'):
        transport.fetch_heads(tmp_path,{REVIEW:'a'*40,MAIN:'b'*40,HEARTBEAT:'--upload-pack=bad'},'run')


def test_fetch_reuses_verified_commits_and_fetches_only_missing_ids(tmp_path,monkeypatch):
    from tools.content_review import coordinator_heartbeat_transport as transport
    review,main,beat='a'*40,'b'*40,'c'*40;heads={REVIEW:review,MAIN:main,HEARTBEAT:beat};calls=[];present={review,main}
    monkeypatch.setattr(transport,'_check_remote',lambda repo:None)
    def run(repo,*args,input_text=None):
        calls.append(args)
        if args[0]=='cat-file':
            ids=[x.removesuffix('^{commit}') for x in input_text.splitlines()]
            return '\n'.join(x+' commit' if x in present else x+'^{commit} missing' for x in ids)
        assert args[:3]==('fetch','--no-tags','--no-write-fetch-head')
        assert args[3:]==('--negotiation-tip='+review,'--negotiation-tip='+main,'origin',beat)
        present.add(beat);return ''
    monkeypatch.setattr(transport,'_run',run)
    transport.fetch_heads(tmp_path,heads,'run')
    assert sum(c[0]=='fetch' for c in calls)==1
    calls.clear();transport.fetch_heads(tmp_path,heads,'run')
    assert all(c[0]=='cat-file' for c in calls)


def test_unexpected_git_object_output_fails_without_fetch(tmp_path,monkeypatch):
    from tools.content_review import coordinator_heartbeat_transport as transport
    monkeypatch.setattr(transport,'_check_remote',lambda repo:None)
    monkeypatch.setattr(transport,'_run',lambda *a,**k:'unexpected object output')
    with pytest.raises(ValueError,match='object verification failed'):
        transport.fetch_heads(tmp_path,{REVIEW:'a'*40,MAIN:'b'*40,HEARTBEAT:'c'*40},'run')


@pytest.mark.parametrize('failure,detail',[
    (subprocess.TimeoutExpired(['git'],45),'Coordinator Git fetch timed_out'),
    (OSError(errno.EAGAIN,'secret private data'),'Coordinator Git fetch resource_unavailable'),
    (subprocess.CalledProcessError(1,['git'],stderr='cannot fork: secret private data'),'Coordinator Git fetch resource_unavailable'),
    (subprocess.CalledProcessError(1,['git'],stderr='Authentication failed: secret private data'),'Coordinator Git fetch access_denied'),
    (subprocess.CalledProcessError(1,['git'],stderr='unexpected secret private data'),'Coordinator Git fetch failed'),
])
def test_git_failures_report_only_safe_fixed_categories(tmp_path,monkeypatch,failure,detail):
    from tools.content_review import coordinator_heartbeat_transport as transport
    def fail(*a,**k):raise failure
    monkeypatch.setattr(transport.subprocess,'run',fail)
    with pytest.raises(ValueError) as error:transport._run(tmp_path,'fetch','origin','private-argument')
    assert str(error.value)==detail and str(error.value) in transport.SAFE_GIT_ERRORS
    assert 'secret' not in str(error.value) and 'private' not in str(error.value)

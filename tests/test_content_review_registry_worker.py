import copy,json
from datetime import timedelta
import pytest,requests
from tools.content_review import registry_worker as w

@pytest.fixture
def packet(tmp_path):
 (tmp_path/'config').mkdir();now=w.now();owner='test-owner'
 state={'phase':'active','lease':{'owner':owner,'expires_at':(now+timedelta(minutes=20)).isoformat()}}
 (tmp_path/'config/content_review_worker_status.json').write_text(json.dumps(state))
 row={'candidate_id':'weekly-test','title':'Verified paper','authors':'A. Author','year':2025,'doi':'10.1234/example','source_url':'https://example.org','abstract':'Verified abstract','document_type':'research_paper','citation_count':None,'decision':'pending'}
 row['content_sha256']=w.digest({k:row.get(k,'') for k in ('title','authors','year','doi','source_url','abstract','document_type')})
 checks={k:{'status':'passed','content_sha256':row['content_sha256'],'checked_at':now.isoformat(),'evidence':{'verified':True}} for k in ('format','access','metadata','duplicates')}
 checks['quality']={'evidence':{'quality_review_status':'hold_below_review_threshold','quality_core_term_gate':'pass','quality_relevance_gate':'pass'}};row['preflight']={'checks':checks}
 manifest=tmp_path/'config/weekly_review_manifest.json';manifest.write_text(json.dumps({'records':[],'preflight_records':[row]}))
 req={'schema_version':1,'created_at':now.isoformat(),'expires_at':(now+timedelta(hours=6)).isoformat(),'lease_owner':owner,'candidate_id':row['candidate_id'],'content_sha256':row['content_sha256'],'doi':row['doi'],'manifest_sha256':w.hashlib.sha256(manifest.read_bytes()).hexdigest(),'gate_evidence_sha256':w.digest({k:checks[k] for k in ('format','access','metadata','duplicates')})};req['request_id']=w.digest(req)
 path=tmp_path/(req['request_id']+'.json');path.write_text(json.dumps(req));return tmp_path,path

def test_missing_secret_never_sends_anonymous_request(packet,monkeypatch):
 monkeypatch.delenv('OPENALEX_API_KEY',raising=False);root,path=packet
 result=w.execute(root,path,get=lambda *a,**k:pytest.fail('anonymous request'))
 assert result['requests']==0 and result['status']=='held'

@pytest.mark.parametrize('status',[200,401,403,429,500])
def test_one_exact_credentialed_request_and_complete_backoff(packet,monkeypatch,status):
 monkeypatch.setenv('OPENALEX_API_KEY','fixture-secret');root,path=packet;calls=[]
 class Response:
  status_code=status;headers={'Retry-After':'86400'}
  def json(self):return {'results':[{'id':'https://openalex.org/W1','doi':'https://doi.org/10.1234/example','title':'Verified paper','cited_by_count':7}]}
 def get(url,**kw):
  calls.append(kw);assert kw['params']['api_key']=='fixture-secret';assert '|' not in kw['params']['filter'];assert kw['timeout']==20 and kw['allow_redirects'] is False;return Response()
 result=w.execute(root,path,get=get);assert len(calls)==result['requests']==1;assert 'fixture-secret' not in json.dumps(result)
 assert result['status']==('complete' if status==200 else 'held')
 if status==429:assert w.datetime.fromisoformat(result['retry_not_before'])>w.now()+timedelta(hours=23)

def test_timeout_never_retries_or_leaks_url(packet,monkeypatch):
 monkeypatch.setenv('OPENALEX_API_KEY','fixture-secret');root,path=packet;calls=[]
 def get(*a,**k):calls.append(1);raise requests.Timeout('URL with fixture-secret')
 result=w.execute(root,path,get=get);assert len(calls)==1 and 'fixture-secret' not in json.dumps(result)

def test_changed_snapshot_fails_before_network(packet,monkeypatch):
 root,path=packet;(root/'config/weekly_review_manifest.json').write_text('{}')
 with pytest.raises(AssertionError):w.execute(root,path,get=lambda *a,**k:pytest.fail('network'))

def test_event_without_file_lists_uses_verified_git_diff(tmp_path,monkeypatch):
 import subprocess
 def git(*args):return subprocess.check_output(['git',*args],cwd=tmp_path,text=True).strip()
 git('init','-q');git('config','user.name','Test');git('config','user.email','test@example.invalid')
 (tmp_path/'base').write_text('base');git('add','base');git('commit','-qm','base');before=git('rev-parse','HEAD')
 directory=tmp_path/w.DIRECTORY;directory.mkdir(parents=True);path=directory/('a'*64+'.json');path.write_text('{}');git('add',w.DIRECTORY);git('commit','-qm','request');after=git('rev-parse','HEAD')
 monkeypatch.setenv('GITHUB_REPOSITORY','RISEInfoSec/Alex');monkeypatch.setenv('GITHUB_REF','refs/heads/'+w.BRANCH);monkeypatch.setenv('GITHUB_SHA',after)
 event={'before':before,'after':after,'ref':'refs/heads/'+w.BRANCH}
 assert w.event_requests(tmp_path,event)==[path]

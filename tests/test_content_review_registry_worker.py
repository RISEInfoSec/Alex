import copy,json
from datetime import timedelta
import pytest
from tools.content_review import registry_worker as w

@pytest.fixture
def packet(tmp_path):
 (tmp_path/'config').mkdir();now=w.now();owner='test-owner'
 pp=tmp_path/'.cache/provider-policy/config';pp.mkdir(parents=True);(pp/'openalex_request_policy.json').write_text('{"requests_enabled":true}')
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

def test_even_a_permissive_policy_cannot_bypass_the_shared_coordinator(packet,monkeypatch):
 monkeypatch.setenv('OPENALEX_API_KEY','fixture-secret');root,path=packet
 result=w.execute(root,path,get=lambda *a,**k:pytest.fail('uncoordinated request'))
 assert result['requests']==0 and result['status']=='held'
 assert 'shared private coordinator' in result['error'] and 'fixture-secret' not in json.dumps(result)

def test_registry_workflow_does_not_supply_provider_credentials():
 from pathlib import Path
 workflow=(Path(__file__).resolve().parents[1]/'.github/workflows/content_review_registry.yml').read_text()
 assert 'OPENALEX_API_KEY' not in workflow and 'HARVEST_MAILTO' not in workflow

def test_owner_pause_and_provider_hold_each_prevent_requests(packet,monkeypatch):
 root,path=packet;monkeypatch.setenv('OPENALEX_API_KEY','fixture-secret')
 policy=root/'.cache/provider-policy/config/openalex_request_policy.json'
 for hold in ({'owner_pause':{'reason':'owner hold'}},{'reconciliation_hold':{'http_status':429}}):
  policy.write_text(json.dumps({'requests_enabled':True,**hold}))
  result=w.execute(root,path,get=lambda *a,**k:pytest.fail('OpenAlex request during hold'))
  assert result['requests']==0 and result['status']=='held' and result['effective_policy']['allowed'] is False

def test_changed_snapshot_fails_before_network(packet,monkeypatch):
 root,path=packet;(root/'config/weekly_review_manifest.json').write_text('{}')
 with pytest.raises(AssertionError):w.execute(root,path,get=lambda *a,**k:pytest.fail('network'))

def test_retired_lifecycle_stops_registry_before_any_request(packet):
 root,path=packet
 (root/'config/content_review_candidate_lifecycle.json').write_text(json.dumps({'records':{'weekly:weekly-test':{'state':'retired_unresolved'}}}))
 with pytest.raises(ValueError,match='Lifecycle prevents work'):
  w.execute(root,path,get=lambda *a,**k:pytest.fail('retired network request'))

def test_event_without_file_lists_uses_verified_git_diff(tmp_path,monkeypatch):
 import subprocess
 def git(*args):return subprocess.check_output(['git',*args],cwd=tmp_path,text=True).strip()
 git('init','-q');git('config','user.name','Test');git('config','user.email','test@example.invalid')
 (tmp_path/'base').write_text('base');git('add','base');git('commit','-qm','base');before=git('rev-parse','HEAD')
 directory=tmp_path/w.DIRECTORY;directory.mkdir(parents=True);path=directory/('a'*64+'.json');path.write_text('{}');git('add',w.DIRECTORY);git('commit','-qm','request');after=git('rev-parse','HEAD')
 monkeypatch.setenv('GITHUB_REPOSITORY','RISEInfoSec/Alex');monkeypatch.setenv('GITHUB_REF','refs/heads/'+w.BRANCH);monkeypatch.setenv('GITHUB_SHA',after)
 event={'before':before,'after':after,'ref':'refs/heads/'+w.BRANCH}
 assert w.event_requests(tmp_path,event)==[path]

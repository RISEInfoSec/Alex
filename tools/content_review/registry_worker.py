"""One credentialed, exact-DOI OpenAlex request; immutable review-only artifact."""
import argparse,hashlib,json,os,re,subprocess
from datetime import datetime,timezone,timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
import requests

DIRECTORY='config/content_review_registry_requests'
BRANCH='codex/soups-corpus-review'
def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
def now():return datetime.now(timezone.utc)
def validate(root,path):
 req=json.loads(path.read_text());assert req['schema_version']==1
 assert digest({k:v for k,v in req.items() if k!='request_id'})==req['request_id'] and path.name==req['request_id']+'.json'
 start=datetime.fromisoformat(req['created_at']);end=datetime.fromisoformat(req['expires_at'])
 assert start.tzinfo and end.tzinfo and start<=now()+timedelta(minutes=5) and now()<end and end-start<=timedelta(hours=6)
 state=json.loads((root/'config/content_review_worker_status.json').read_text());lease=state['lease']
 assert state['phase']=='active' and lease['owner']==req['lease_owner'] and datetime.fromisoformat(lease['expires_at'].replace('Z','+00:00'))>now()
 cooldown=state.get('source_backoff',{}).get('OpenAlex',{}).get('retry_not_before')
 if cooldown:assert datetime.fromisoformat(cooldown.replace('Z','+00:00'))<=now()
 manifest=root/'config/weekly_review_manifest.json';assert hashlib.sha256(manifest.read_bytes()).hexdigest()==req['manifest_sha256']
 m=json.loads(manifest.read_text());row=next(r for r in m.get('records',[])+m.get('preflight_records',[]) if r['candidate_id']==req['candidate_id'])
 fields=('title','authors','year','doi','source_url','abstract','document_type')
 assert digest({k:row.get(k,'') for k in fields})==row['content_sha256']==req['content_sha256']
 assert row.get('decision','pending') in ('pending','unreviewed') and row.get('citation_count') is None
 assert row['document_type']=='research_paper' and row['doi']==req['doi'] and re.fullmatch(r'10\.\d{4,9}/[^\s|]+',req['doi'])
 checks=row['preflight']['checks'];gates=('format','access','metadata','duplicates')
 for gate in gates:
  c=checks[gate];assert c['status']=='passed' and c['content_sha256']==req['content_sha256'] and c.get('checked_at') and c.get('evidence') and not c.get('stale')
 assert digest({k:checks[k] for k in gates})==req['gate_evidence_sha256']
 q=checks['quality']['evidence'];assert q['quality_review_status']=='hold_below_review_threshold' and q['quality_core_term_gate']==q['quality_relevance_gate']=='pass'
 return req

def execute(root,path,get=None):
 req=validate(root,path)
 result={'schema_version':1,'request_id':req['request_id'],'candidate_id':req['candidate_id'],'content_sha256':req['content_sha256'],'checked_at':now().isoformat(),'status':'held','requests':0,'corpus_modified':False,'publication_approved':False,'provenance':{k:os.environ.get(k,'') for k in ['GITHUB_SHA','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_REF','GITHUB_WORKFLOW_REF']}}
 key=os.environ.get('OPENALEX_API_KEY','')
 if not key:result['error']='Repository OPENALEX_API_KEY unavailable to isolated workflow; no anonymous request sent.';return result
 result['credential_path']='Existing repository OPENALEX_API_KEY secret -> OPENALEX_API_KEY environment -> api_key request parameter'
 params={'filter':'doi:https://doi.org/'+req['doi'],'per-page':1,'select':'id,doi,title,publication_year,authorships,cited_by_count','api_key':key}
 contact=os.environ.get('HARVEST_MAILTO','')
 if contact:params['mailto']=contact
 result['requests']=1
 try:
  response=(get or requests.get)('https://api.openalex.org/works',params=params,headers={'User-Agent':'ALEX-ContentReview/1.0 (+https://github.com/RISEInfoSec/Alex)','Accept':'application/json'},timeout=20,allow_redirects=False)
 except requests.RequestException as exc:
  result['error']='OpenAlex '+type(exc).__name__+'; provider stopped without retry.';return result
 result['http_status']=response.status_code
 if response.status_code!=200:
  result['error']='OpenAlex HTTP'+str(response.status_code)+'; provider stopped without retry.'
  retry=response.headers.get('Retry-After')
  if retry:
   try:
    end=now()+timedelta(seconds=max(0,float(retry)))
   except ValueError:
    try:end=parsedate_to_datetime(retry).astimezone(timezone.utc)
    except (ValueError,TypeError):end=None
   if end:result['retry_not_before']=end.isoformat()
  return result
 try:
  data=response.json();results=data.get('results',[])
  if len(results)!=1:result['error']='Exact DOI lookup returned no unique work.';return result
  work=results[0];assert work.get('doi','').lower()=='https://doi.org/'+req['doi'].lower()
  count=work.get('cited_by_count');assert isinstance(count,int) and not isinstance(count,bool) and count>=0
  result.update(status='complete',work={k:work.get(k) for k in ['id','doi','title','publication_year','authorships','cited_by_count']})
 except (ValueError,TypeError,AttributeError,AssertionError):result['error']='OpenAlex response failed exact identity/count validation.'
 return result

def event_requests(root,event):
 if os.environ.get('GITHUB_REPOSITORY')!='RISEInfoSec/Alex' or os.environ.get('GITHUB_REF')!='refs/heads/'+BRANCH or event.get('ref')!='refs/heads/'+BRANCH or event.get('deleted'):raise ValueError('Review branch push required')
 before,after=event['before'],event['after']
 if after!=os.environ.get('GITHUB_SHA') or not all(re.fullmatch('[0-9a-f]{40}',x) for x in (before,after)):raise ValueError('Event commit mismatch')
 lines=subprocess.check_output(['git','diff','--name-status',before,after,'--',DIRECTORY],cwd=root,text=True).splitlines();paths=[]
 for line in lines:
  change,path=line.split('\t',1)
  if change!='A' or not re.fullmatch(DIRECTORY+r'/[0-9a-f]{64}\.json',path):raise ValueError('Registry requests are immutable additions only')
  paths.append(root/path)
 if len(paths)!=1:raise ValueError('Exactly one immutable registry request per run required')
 return paths

def main():
 p=argparse.ArgumentParser();p.add_argument('--event',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();root=Path.cwd();event=json.loads(a.event.read_text());paths=event_requests(root,event)
 if a.output.resolve().is_relative_to(root/'data') or a.output.resolve().is_relative_to(root/'config'):raise ValueError('Output must remain an artifact outside corpus/config')
 result=execute(root,paths[0]);a.output.parent.mkdir(parents=True,exist_ok=True);content=json.dumps(result,ensure_ascii=False,indent=2)+'\n';a.output.write_text(content)
 print('CONTENT_REVIEW_REGISTRY_RESULT_JSON='+json.dumps(result,ensure_ascii=False));print('CONTENT_REVIEW_REGISTRY_RESULT_SHA256='+hashlib.sha256(content.encode()).hexdigest())

if __name__=='__main__':main()

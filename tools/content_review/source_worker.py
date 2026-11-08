"""Bounded, read-only source evidence worker. No gate passes or corpus writes.

Run in the established GitHub Actions transport. The coordinator remains the
only writer. Source content is untrusted data and never executed as instructions.
"""
from __future__ import annotations
import argparse, hashlib, io, ipaddress, json, os, re, signal, socket, subprocess, time
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlsplit, urljoin, urldefrag
from urllib.robotparser import RobotFileParser
def digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
def reviewed_digest(row):
    return digest({k:row.get(k,'') for k in ('title','authors','year','doi','source_url','abstract','document_type')})
def records(manifest):return manifest.get('records',[])+manifest.get('preflight_records',[])
def file_digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
MANIFESTS={s:'config/'+s+'_review_manifest.json' for s in ('soups','weekly','first','m3aawg','bellingcat','sans','virusbulletin')}

from tools.content_review.lifecycle import ensure_eligible, instant
from tools.content_review.source_origin_backoff import active as origin_backoff_active, origin as canonical_origin
from tools.content_review.source_unresolved import validate as validate_unresolved

DIRECTORY = 'config/content_review_source_requests'
WORKFLOW = '.github/workflows/content_review_sources.yml'
BRANCH = 'codex/soups-corpus-review'
UA = 'ALEX-ContentReview/2.0 (+https://github.com/RISEInfoSec/Alex)'
MAX_BYTES = 12 * 1024 * 1024

class Hold(Exception):
    pass

def safe_url(url, resolve=True):
    p=urlsplit(url)
    if p.scheme not in ('https','http') or not p.hostname or p.username or p.password or p.port not in (None,443 if p.scheme=='https' else 80):
        raise Hold('unsupported_or_credentialed_url')
    host=p.hostname.rstrip('.')
    # OpenAlex has a dedicated, bounded policy-aware route. Generic source
    # retrieval must not bypass its shared pacing and per-run budget.
    if host=='openalex.org' or host.endswith('.openalex.org'):
        raise Hold('openalex_requires_controlled_route')
    if host=='api.openai.com':
        raise Hold('provider_requires_separate_controlled_route')
    if resolve:
        try: addresses={a[4][0] for a in socket.getaddrinfo(p.hostname,443 if p.scheme=='https' else 80,type=socket.SOCK_STREAM)}
        except OSError: raise Hold('dns_resolution_failed')
        if not addresses or any(not ipaddress.ip_address(a).is_global for a in addresses):
            raise Hold('nonpublic_destination')
    return urldefrag(url)[0]

def retry_at(value):
    if not value:return None
    try:return (datetime.now(timezone.utc)+timedelta(seconds=max(0,float(value)))).isoformat()
    except ValueError:
        try:return parsedate_to_datetime(value).astimezone(timezone.utc).isoformat()
        except (ValueError,TypeError):return None

class Transport:
    def __init__(self, *, deadline, cap=30, session=None, clock=time.monotonic, sleep=time.sleep, origin_backoff=None, unresolved_origins=None):
        import requests
        self.deadline,self.cap,self.session,self.clock,self.sleep=deadline,cap,session or requests.Session(),clock,sleep
        self.origin_backoff=origin_backoff if origin_backoff is not None else {}
        self.unresolved_origins=unresolved_origins if unresolved_origins is not None else set()
        self.sends=[];self.last={};self.robots={};self.stopped={};self.cache={}
        self.session.headers.update({'User-Agent':UA,'Accept':'text/html,application/pdf;q=0.9,*/*;q=0.1'})
    def send(self,url):
        import requests
        url=safe_url(url,resolve=False);origin=canonical_origin(url)
        if origin in self.unresolved_origins:raise Hold('source_outcome_requires_reconciliation')
        url=safe_url(url)
        if origin_backoff_active(self.origin_backoff,url,datetime.now(timezone.utc)):
            raise Hold('source_origin_backoff_active')
        if origin in self.stopped:raise Hold('origin_backoff: '+self.stopped[origin]['reason'])
        delay=max(0,2-(self.clock()-self.last.get(origin,-100)))
        if len(self.sends)>=self.cap or self.clock()+delay+20>=self.deadline:raise Hold('source_request_or_time_budget_exhausted')
        self.sleep(delay)
        event={'url':url,'started_at':datetime.now(timezone.utc).isoformat()};self.sends.append(event)
        previous=signal.getsignal(signal.SIGALRM)
        def timed_out(*_):raise TimeoutError('source_deadline')
        signal.signal(signal.SIGALRM,timed_out);signal.setitimer(signal.ITIMER_REAL,20)
        try:
            with self.session.get(url,timeout=20,allow_redirects=False,stream=True) as response:
                event['http_status']=response.status_code
                headers={k.lower():v for k,v in response.headers.items() if k.lower() in ('content-type','etag','last-modified','retry-after','location')}
                if 'location' in headers:event['redirect_location']=urljoin(url,headers['location'])
                event['retry_not_before']=retry_at(headers.get('retry-after'))
                if response.status_code==429 or response.status_code>=500:
                    self.stopped[origin]={'reason':'http_'+str(response.status_code),'retry_not_before':event['retry_not_before'] or (datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}
                chunks=[];size=0
                for b in response.iter_content(65536):
                    size+=len(b)
                    if size>MAX_BYTES:raise Hold('source_size_limit')
                    chunks.append(b)
                body=b''.join(chunks);event['bytes']=len(body)
                return response.status_code,headers,body
        except (requests.RequestException,TimeoutError) as exc:
            event['error']=type(exc).__name__
            self.stopped[origin]={'reason':'transport_'+type(exc).__name__,'retry_not_before':(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()}
            raise Hold(event['error']) from None
        finally:
            signal.setitimer(signal.ITIMER_REAL,0);signal.signal(signal.SIGALRM,previous);self.last[origin]=self.clock()
    def permitted(self,url):
        p=urlsplit(url);origin=p.scheme+'://'+p.netloc
        if origin not in self.robots:
            robots_url=origin+'/robots.txt'
            for _ in range(6):
                status,headers,body=self.send(robots_url)
                if status in (301,302,303,307,308) and headers.get('location'):
                    robots_url=safe_url(urljoin(robots_url,headers['location']));continue
                break
            else:raise Hold('robots_redirect_limit')
            if status in (404,410):rp=None
            elif status==200:
                rp=RobotFileParser();rp.parse(body.decode('utf-8','replace').splitlines())
            else:raise Hold('robots_unavailable_http_'+str(status))
            self.robots[origin]=rp
        rp=self.robots[origin]
        if rp and not rp.can_fetch(UA,url):raise Hold('robots_disallow')
        crawl=rp.crawl_delay(UA) if rp else None
        if crawl and crawl>2:
            delay=max(0,crawl-(self.clock()-self.last.get(canonical_origin(url),-100)))
            if self.clock()+delay+20>=self.deadline:raise Hold('crawl_delay_exceeds_budget')
            self.sleep(delay)
    def fetch(self,url):
        original=url;chain=[]
        for _ in range(6):
            url=safe_url(url)
            if url in self.cache:return {**self.cache[url],'cache_reused':True,'requested_url':original}
            self.permitted(url)
            status,headers,body=self.send(url);chain.append({'url':url,'http_status':status})
            if status in (301,302,303,307,308) and headers.get('location'):
                url=urljoin(url,headers['location']);continue
            if status!=200:raise Hold('source_http_'+str(status))
            result={'requested_url':original,'final_url':url,'http_status':status,'headers':headers,'redirects':chain,'body':body,'body_sha256':hashlib.sha256(body).hexdigest()}
            self.cache[url]=result;return result
        raise Hold('redirect_limit')

def extract(response, fragment=''):
    body=response['body'];out={k:v for k,v in response.items() if k!='body'}
    out['retrieved_at']=datetime.now(timezone.utc).isoformat();out['byte_count']=len(body)
    if response.get('headers', {}).get('content-type', '').split(';')[0] == 'application/json':
        try: data=json.loads(body)
        except (ValueError,UnicodeDecodeError): raise Hold('invalid_source_json') from None
        # Full authoritative metadata remains intact, even when its title is anomalously long.
        if not isinstance(data,dict):raise Hold('unsupported_metadata_json')
        datacite=data.get('data',{})
        if urlsplit(response['final_url']).hostname=='api.datacite.org' and isinstance(datacite,dict):
            metadata=datacite.get('attributes')
            if not isinstance(metadata,dict):raise Hold('unsupported_metadata_json')
            record_id,doi=datacite.get('id'),metadata.get('doi')
        else:
            metadata=data.get('metadata');record_id,doi=data.get('id'),data.get('doi')
            if not isinstance(metadata,dict):raise Hold('unsupported_metadata_json')
        text=json.dumps(metadata,ensure_ascii=False)
        out.update(container_type='json',metadata=metadata,repository_record_id=record_id,
                   repository_doi=doi,files=data.get('files',[]),links=data.get('links',{}),
                   text=text[:36000],text_complete=len(text)<=36000,metadata_complete=True,document_type='unverified')
    elif body.startswith(b'%PDF-'):
        from pypdf import PdfReader
        try:
            pdf=PdfReader(io.BytesIO(body));pages=[p.extract_text() or '' for p in pdf.pages[:6]]
        except Exception:raise Hold('pdf_parse_failed') from None
        text='\n'.join(pages)
        out.update(container_type='pdf',page_count=len(pdf.pages),pages_inspected=len(pages),pdf_metadata={str(k):str(v) for k,v in (pdf.metadata or {}).items()},text=text[:36000],text_complete=len(pdf.pages)<=6 and len(text)<=36000,document_type='unverified')
    else:
        from bs4 import BeautifulSoup
        soup=BeautifulSoup(body,'html.parser')
        text0=soup.get_text(' ',strip=True)
        if re.search(r'(?i)(just a moment|verify you are human|enable javascript and cookies to continue|access denied)',(soup.title.get_text() if soup.title else '')+' '+text0[:400]):raise Hold('access_challenge')
        metadata={}
        for tag in soup.find_all('meta'):
            name=tag.get('name') or tag.get('property')
            if name and tag.get('content'):metadata.setdefault(name.lower(),[]).append(tag['content'])
        section=soup
        if fragment:
            anchor=soup.find(id=fragment) or soup.find(attrs={'name':fragment})
            if anchor is None:raise Hold('candidate_fragment_not_found')
            # FIRST item wrappers hold one contribution and its explicit asset links.
            section=anchor if anchor.name in ('article','section') else anchor.find_parent(['article','section']) or anchor.parent
            if anchor.name not in ('article','section') and len(section.get_text(' ',strip=True))<120:
                nodes=[str(anchor)]
                for sibling in anchor.next_siblings:
                    if getattr(sibling,'name',None) in ('h2','h3','h4'):break
                    nodes.append(str(sibling))
                section=BeautifulSoup(''.join(nodes),'html.parser')
        links=[{'text':a.get_text(' ',strip=True),'url':urljoin(response['final_url'],a['href'])} for a in section.find_all('a',href=True)]
        for tag in section(['script','style','nav','footer','header','noscript']):tag.decompose()
        text=section.get_text('\n',strip=True)
        title=soup.title.get_text(' ',strip=True) if soup.title else ''
        unavailable=bool(re.search(r'(?i)(temporarily unavailable for review|temporarily unavailable.*content review)',title+' '+text0[:3000]))
        out.update(container_type='html',metadata=metadata,title=title,links=links[:200],text=text[:36000],text_complete=len(text)<=36000,document_type='unverified',fragment=fragment,resource_unavailable=unavailable)
    out['text_sha256']=hashlib.sha256(out['text'].encode()).hexdigest()
    if not out['text'].strip():raise Hold('no_extractable_text_ocr_required')
    return out

def linked_pdf(source):
    """Only publisher citation metadata or a verified candidate fragment binds assets.

    A global navigation/footer PDF never establishes candidate identity.
    """
    if source.get('resource_unavailable'):raise Hold('publisher_temporarily_withheld_for_review')
    if source['container_type']=='json':
        pdfs=[f.get('links',{}).get('self') for f in source.get('files',[])
              if str(f.get('key','')).lower().endswith('.pdf')]
        return pdfs[0] if len(pdfs)==1 and pdfs[0] else None
    if source['container_type']!='html':return None
    pdfs=source.get('metadata',{}).get('citation_pdf_url',[])
    if not pdfs and source.get('fragment'):
        pdfs=[a['url'] for a in source.get('links',[]) if re.search(r'(?i)\.pdf(?:$|[?#])',a['url'])]
    return urljoin(source['final_url'],pdfs[0]) if len(pdfs)==1 else None

def validate_corpus_snapshot(root,req):
    """Read-only evidence for existing publications; never fake intake identities."""
    if req.get('snapshot_path') != 'config/content_review_corpus_metadata_snapshot.json':
        raise ValueError('Unexpected corpus snapshot path')
    path=root/req['snapshot_path']
    if file_digest(path)!=req.get('snapshot_sha256'):raise ValueError('Changed corpus snapshot')
    snapshot=json.loads(path.read_text())
    if not re.fullmatch(r'[0-9a-f]{64}',snapshot.get('public_json_sha256','')) or not snapshot.get('source_commit'):
        raise ValueError('Missing live corpus provenance')
    for item in req['records']:
        if item.get('collection')!='corpus_metadata_audit':raise ValueError('Invalid corpus evidence route')
        matches=[r for r in snapshot['records'] if str(r['id'])==item['candidate_id']]
        if len(matches)!=1 or digest(matches[0])!=item['content_sha256']:
            raise ValueError('Changed corpus record')
        doi=str(matches[0].get('doi','')).lower()
        match=re.fullmatch(r'10\.5281/zenodo\.(\d+)',doi)
        permitted={'https://zenodo.org/api/records/'+match.group(1)} if match else set()
        if item['url'] not in permitted:
            raise ValueError('Corpus URL does not match DOI')


def validate(root,path):
    req=json.loads(path.read_text());payload={k:v for k,v in req.items() if k!='request_id'}
    if req.get('schema_version')!=1 or digest(payload)!=req.get('request_id') or path.name!=req['request_id']+'.json':raise ValueError('Invalid immutable source request')
    end=instant(req.get('work_deadline'));start=instant(req.get('started_at'));now=datetime.now(timezone.utc)
    if not start or not end or not start<=now<end or (end-start).total_seconds()>600:raise ValueError('Expired or unbounded source work')
    state=json.loads((root/'config/content_review_worker_status.json').read_text());lease=state.get('lease') or {}
    if lease.get('owner')!=req['lease_owner'] or not instant(lease.get('expires_at')) or instant(lease['expires_at'])<=now:raise ValueError('No matching unexpired writer lease')
    if 'coordinator_run_id' in req:
        current=state.get('current_run') or {};pending=current.get('pending_source_request') or {};counts=current.get('request_counts') or {}
        if (not isinstance(req['coordinator_run_id'],str) or not req['coordinator_run_id']
            or lease.get('run_id')!=req['coordinator_run_id'] or current.get('run_id')!=req['coordinator_run_id']
            or current.get('application_status')!='running' or instant(current.get('started_at'))!=start
            or pending.get('request_id')!=req['request_id'] or pending.get('origin_run_id')!=req['coordinator_run_id']
            or pending.get('reserved_limit')!=req.get('source_request_limit')
            or type(counts.get('source')) is not int or not 0<=counts['source']<30
            or type(req.get('source_request_limit')) is not int or req['source_request_limit']!=30-counts['source']
            or type(counts.get('paid')) is not int or not 0<=counts['paid']<=5
            or type(counts.get('openalex')) is not int or counts['openalex']!=0):
            raise ValueError('Matching single pending source request and budget are required')
    items=req['records']
    if not 1<=len(items)<=5 or len({i['candidate_id'] for i in items})!=len(items):raise ValueError('Initial pilot candidate ceiling/identity')
    unresolved_keys,unresolved_hosts=validate_unresolved(state.get('source_unresolved_requests',[]))
    for item in items:
        if (item.get('collection'),item.get('candidate_id')) in unresolved_keys or canonical_origin(item.get('url')) in unresolved_hosts:
            raise ValueError('Source outcome requires reconciliation')
        if origin_backoff_active(state.get('source_origin_backoff',{}),item.get('url'),now):
            raise ValueError('Source origin cooldown is active')
    if req.get('purpose') == 'corpus_metadata_audit':
        validate_corpus_snapshot(root,req)
        return req
    if req.get('purpose') not in (None,'candidate_source_evidence'):
        raise ValueError('Unsupported source request purpose')
    for item in items:
        p=root/MANIFESTS[item['collection']]
        if file_digest(p)!=item['manifest_sha256']:raise ValueError('Incomplete or changed manifest snapshot')
        matches=[r for r in records(json.loads(p.read_text())) if r['candidate_id']==item['candidate_id']]
        if len(matches)!=1:raise ValueError('Candidate missing/nonunique')
        row=matches[0];ensure_eligible(root,item['collection'],item['candidate_id'])
        if row['content_sha256']!=item['content_sha256'] or reviewed_digest(row)!=row['content_sha256']:raise ValueError('Candidate content changed')
        evidence=row.get('source_processing',{})
        if evidence.get('content_sha256')==row['content_sha256'] and evidence.get('retrieval_status') in ('retrieved','held'):
            raise ValueError('Retained source evidence or hold must be resolved first')
        if row.get('decision','pending') not in ('pending','unreviewed'):raise ValueError('Decided candidate')
        if item['url']!=row['source_url']:
            ref=item.get('resume_receipt','')
            if not re.fullmatch(r'config/content_review_source_receipts/[0-9a-f]{64}\.json',ref):raise ValueError('Unbound source URL')
            receipt=json.loads((root/ref).read_text())
            if receipt.get('independently_verified') is not True:raise ValueError('Unverified prior source receipt')
            prior=[r for r in receipt['result']['records'] if r['candidate_id']==row['candidate_id'] and r['content_sha256']==row['content_sha256']]
            links=[a['url'] for r in prior for e in r['evidence'] for a in e.get('links',[])]
            if item['url'] not in links:raise ValueError('Asset URL absent from verified original source')
        if str(row.get('source_observation',{}).get('tlp','')).upper() not in ('','TLP:CLEAR','TLP:WHITE'):raise ValueError('Restricted TLP')
        if row.get('access_decision',{}).get('status')=='restricted':raise ValueError('Access restricted')
    return req

def execute(root,path,output):
    req=validate(root,path);seconds=(instant(req['work_deadline'])-datetime.now(timezone.utc)).total_seconds()
    state=json.loads((root/'config/content_review_worker_status.json').read_text())
    _,unresolved_origins=validate_unresolved(state.get('source_unresolved_requests',[]))
    tx=Transport(deadline=time.monotonic()+seconds,cap=min(30,req['source_request_limit']),
                 origin_backoff=state.get('source_origin_backoff',{}),unresolved_origins=unresolved_origins)
    result={'schema_version':1,'request_id':req['request_id'],'status':'running','records':[],'requests':0,'read_only':True,'provenance':{k:os.environ.get(k,'') for k in ('GITHUB_SHA','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT','GITHUB_REF','GITHUB_WORKFLOW_REF')}}
    def checkpoint():
        result.update(requests=len(tx.sends),request_log=tx.sends,origin_backoff=tx.stopped,updated_at=datetime.now(timezone.utc).isoformat())
        output.parent.mkdir(parents=True,exist_ok=True);tmp=output.with_suffix('.tmp');tmp.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');tmp.replace(output)
    for item in req['records']:
        row={k:item[k] for k in ('collection','candidate_id','content_sha256')};row.update(status='held',evidence=[])
        try:
            source=extract(tx.fetch(item['url']),urlsplit(item['url']).fragment);row['evidence'].append(source)
            pdf=linked_pdf(source)
            if pdf:
                asset=extract(tx.fetch(pdf));row['evidence'].append(asset)
                linked_pdf(asset) # Detect a publisher's HTML hold page replacing the asset.
            row.update(status='retrieved',next_action='Inspect actual content and identity; evidence retrieval alone passes no gate.')
        except Hold as exc:row.update(reason=str(exc),next_action='Respect access/backoff; inspect retained partial evidence or repair the specific capability. Do not repeat completed retrieval.')
        result['records'].append(row);checkpoint()
    result['status']='complete';checkpoint();return result

def event_request(root,event):
    if os.environ.get('GITHUB_REF')!='refs/heads/'+BRANCH or event.get('ref')!='refs/heads/'+BRANCH or event.get('after')!=os.environ.get('GITHUB_SHA'):raise ValueError('Review push identity required')
    changes=subprocess.check_output(['git','diff','--name-status',event['before'],event['after'],'--',DIRECTORY],cwd=root,text=True).splitlines()
    if len(changes)!=1 or not re.fullmatch('A\\t'+DIRECTORY+r'/[0-9a-f]{64}\.json',changes[0]):raise ValueError('Exactly one immutable new source request')
    return root/changes[0].split('\t')[1]

def main():
    p=argparse.ArgumentParser();p.add_argument('--event',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();root=Path.cwd()
    if a.output.resolve().is_relative_to(root/'config') or a.output.resolve().is_relative_to(root/'data'):raise ValueError('Artifact output only')
    path=event_request(root,json.loads(a.event.read_text()));result=execute(root,path,a.output)
    print('CONTENT_REVIEW_SOURCE_RESULT_JSON='+json.dumps(result,ensure_ascii=False));print('CONTENT_REVIEW_SOURCE_RESULT_SHA256='+file_digest(a.output))
if __name__=='__main__':main()

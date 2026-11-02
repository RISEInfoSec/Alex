"""Source adapters for existing Content Review inventory and weekly preflight.
Never approves, changes thresholds, calls a model or writes public corpus data.
"""
from __future__ import annotations
import argparse, copy, csv, hashlib, json, os, re, time
from collections import Counter
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit, urlunsplit, parse_qsl, urlencode
from urllib.robotparser import RobotFileParser
from zoneinfo import ZoneInfo
import xml.etree.ElementTree as ET
import requests
from bs4 import BeautifulSoup
from alex.editorial_exclusions import record_keys, load_keys

ROOT=Path(__file__).resolve().parents[2]
UA='ALEX-ContentReview/1.1 (+https://alex.riseinfosec.org/; https://github.com/RISEInfoSec/Alex)'
SOURCE_LABELS={'first':'FIRST','m3aawg':'M3AAWG','bellingcat':'Bellingcat','consensus':'Consensus'}
GATES=('format','access','metadata','duplicates','quality','schema')
HASH_FIELDS=('title','authors','year','doi','source_url','abstract','document_type')
def stamp(): return datetime.now(timezone.utc).isoformat()
def digest(v): return hashlib.sha256(json.dumps(v,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
def canonical(v):
    u=urlsplit(v)
    if u.scheme not in ('http','https') or not u.hostname or u.username or u.password:return ''
    q=[(k,v) for k,v in parse_qsl(u.query) if not k.lower().startswith('utm_') and k not in ('fbclid','gclid')]
    return urlunsplit(('https',u.netloc.lower(),u.path.rstrip('/'),urlencode(sorted(q)),u.fragment))
def year_of(v):
    m=re.search(r'\b(?:19|20)\d{2}\b',str(v or ''))
    return int(m[0]) if m else None
def text(n):return n.get_text(' ',strip=True) if n else ''
def candidate(sid,url,title,**kw):
    return dict(source_id=sid,source_url=canonical(url),title=' '.join(title.split()),
                authors=kw.pop('authors',''),year=kw.pop('year',None),doi=kw.pop('doi',''),abstract=kw.pop('abstract',''),**kw)

def first_page(body,url):
    s=BeautifulSoup(body,'html.parser');rows=[];links=[]
    for item in s.select('li.search-item'):
        h=item.select_one('h3');title=item.get('data-title') or text(h)
        if not title or not h or not h.get('id'):continue
        abstract=copy.copy(item.select_one('.p-abstract'))
        if abstract:
            for bio in abstract.select('blockquote'):bio.decompose()
        date=text(item.select_one('[itemprop="startDate"]'));tlp=text(item.select_one('.tlp')).upper()
        restricted=tlp not in ('','TLP:CLEAR','TLP:WHITE')
        resources=[dict(url=urljoin(url,a.get('href') or a.get('src')),kind='recording_candidate' if a.name=='source' else 'format_unverified') for a in item.select('.files a[href], .files source[src]')]
        rows.append(candidate('first',url.split('#')[0]+'#'+h['id'],title,authors=item.get('data-speakers',''),
            year=year_of(date),abstract='' if restricted else text(abstract),publication_date_observed=date,
            venue=text(item.select_one('.p-event')),publisher='FIRST',observed_document_type='conference_contribution',
            resources=resources,tlp=tlp,access_restriction='TLP restriction; public reuse not established' if restricted else
            'Historical presentation files restricted; verify current FIRST policy before retrieval',
            presentation_policy_url='https://www.first.org/resources/presentation-access'))
    if '/guides' in url or '/standards' in url:
        main=s.select_one('#main') or s.select_one('#body') or s
        for h in main.select('h2[id], h3[id]'):
            title=text(h);resources=[]
            if not title or title=='Publications on Spotlight':continue
            for sibling in h.next_siblings:
                if getattr(sibling,'name',None) in ('h2','h3'):break
                if hasattr(sibling,'select'):
                    resources.extend(dict(url=urljoin(url,a['href']),kind='format_unverified') for a in sibling.select('a[href]') if not a['href'].startswith('#'))
            if resources:rows.append(candidate('first',url.split('#')[0]+'#'+h['id'],title,publisher='FIRST',
                observed_document_type='technical_guide_or_standard',resources=resources))
    for a in s.select('a[href]'):
        target=urljoin(url,a['href'])
        if re.search(r'/resources/papers/(?:19|20)\d{2}$',target):links.append(target)
    return rows,links

def m3aawg_page(body,url):
    s=BeautifulSoup(body,'html.parser');main=s.find('main') or s;rows=[];consumed=set()
    for item in main.select('.doc'):
        a=item.select_one('a.title[href]')
        if not a:continue
        times=item.select('time[datetime]');date=times[-1]['datetime'][:10] if times else ''
        title=text(a);target=urljoin(url,a['href']);consumed.add(canonical(target))
        lang=re.match(r'^In (Japanese|Spanish|Portuguese|French|German|Chinese|Arabic|Russian)\b',title,re.I)
        rows.append(candidate('m3aawg',target,title,year=year_of(date),abstract=text(item.select_one('.headline')),
            publication_date_observed=date,publisher='M3AAWG',
            observed_document_type='policy_research_candidate' if 'published-comments' in url else 'best_practice_guide_candidate',
            language=lang[1].lower() if lang else 'unverified',
            related_version_urls=[urljoin(url,x['href']) for x in item.select('.headline a[href]')],
            edition_note='Reconcile latest edition and translations before creating a public record'))
    if 'supporting-documents' in url:
        for a in main.select('a[href]'):
            title=text(a);target=canonical(urljoin(url,a['href']))
            if not title or target in consumed or not re.search(r'\.pdf(?:$|\?)',target,re.I):continue
            consumed.add(target)
            rows.append(candidate('m3aawg',target,title,year=year_of(title+' '+target),publisher='',
                observed_document_type='supporting_document_candidate',
                attribution_status='Original authors/publisher require front matter verification; M3AAWG is discovery host',
                metadata_conflict='2026 listing points to a 2025 file' if '2026' in title and '2025' in target else ''))
    return rows,[urljoin(url,a['href']) for a in main.select('.pager a[href]')]

def bellingcat_page(body,url):
    rows=[]
    if '<rss' in body or '<urlset' in body or '<sitemapindex' in body:
        root=ET.fromstring(body)
        if root.tag.endswith('sitemapindex'):
            return [],[e.text for e in root.iter() if e.tag.endswith('loc') and re.search(r'/post-sitemap\d*\.xml$',e.text or '')]
        if root.tag.endswith('urlset'):
            for el in root:
                values={e.tag.split('}')[-1]:e.text for e in el};target=values.get('loc','')
                if re.search(r'/resources/(?:how-tos/)?20\d{2}/',target):
                    rows.append(candidate('bellingcat',target,'',year=year_of(target),publisher='Bellingcat',
                        observed_document_type='osint_methodology_candidate',source_modified_at=values.get('lastmod',''),
                        metadata_status='Sitemap URL only; title/author/content verification pending'))
            return rows,[]
        for item in root.findall('.//item'):
            title=item.findtext('title') or '';target=item.findtext('link') or ''
            cats=' '.join(e.text or '' for e in item.findall('category'))
            authors=[e.text or '' for e in item if e.tag.endswith('creator')]
            try:date=parsedate_to_datetime(item.findtext('pubDate')).isoformat()
            except (ValueError,TypeError):date=''
            method='/resources/' in target or bool(re.search(r'geolocat|verif|method|forensic|open.source|satellite',cats,re.I))
            promo=bool(re.search(r'\b(workshop|fundrais|newsletter|ticket|vacanc|hiring)\b',title,re.I))
            rows.append(candidate('bellingcat',target,title,authors='; '.join(authors),year=year_of(date),
                abstract=text(BeautifulSoup(item.findtext('description') or '','html.parser')),publisher='Bellingcat',
                publication_date_observed=date,observed_document_type='osint_methodology_candidate' if '/resources/' in target else 'investigative_case_study_candidate',
                methodology_signal=method,intake_exclusion='routine_news_or_promotion' if promo or not method else '',
                peer_review_status='Investigative journalism; peer review not claimed'))
        return rows,[]
    s=BeautifulSoup(body,'html.parser')
    for a in s.select('article h3 a[href]'):
        if '/resources/' in a['href']:
            rows.append(candidate('bellingcat',a['href'],text(a),year=year_of(a['href']),publisher='Bellingcat',
                observed_document_type='osint_methodology_candidate',peer_review_status='Investigative journalism; peer review not claimed'))
    return rows,[]

def consensus_results(data):
    if not isinstance(data,dict) or not isinstance(data.get('results'),list):raise ValueError('Unexpected Consensus schema')
    rows=[]
    for item in data['results']:
        doi=re.sub(r'^https?://(?:dx\.)?doi.org/','',item.get('doi') or '',flags=re.I)
        target=item.get('url') or ('https://doi.org/'+doi if doi else '')
        if not target or not item.get('title'):continue
        rows.append(candidate('consensus',target,item['title'],doi=doi,authors='; '.join(item.get('authors') or []),
            year=item.get('publish_year'),abstract=item.get('abstract') or '',venue=item.get('journal_name') or '',
            publisher=item.get('publisher_name') or '',affiliations='; '.join(item.get('institutions') or []),
            citation_count=item.get('citation_count'),is_preprint=item.get('is_preprint'),
            observed_document_type='academic_paper_candidate',discovery_intermediary='Consensus',
            publication_date_observed=item.get('publish_date') or ''))
    return rows

def consensus_search(source,state,checkpoint,request=requests.get):
    key=os.getenv('CONSENSUS_API_KEY')
    if not key or os.getenv('CONSENSUS_FREE_PLAN_CONFIRMED')!='true':
        raise ValueError('Secure key and verified Free account confirmation required; paid accounts disabled')
    period=datetime.now(ZoneInfo('America/Toronto')).strftime('%Y-%m')
    usage=state.setdefault('consensus_usage',{})
    if usage.get('period')!=period:usage.clear();usage.update(period=period,attempted_calls=0)
    cap=min(30,int(source.get('monthly_call_cap',24)));rows=[]
    for query in source['queries']:
        if usage['attempted_calls']>=cap:break
        usage['attempted_calls']+=1;checkpoint()
        r=request('https://api.consensus.app/v1/search',params={'query':query,'page':1},
            headers={'x-api-key':key,'User-Agent':UA},timeout=20,allow_redirects=False)
        if r.status_code!=200:raise ValueError('Consensus failed; no metered retry')
        found=consensus_results(r.json())
        for row in found:row['discovery_query']=query
        rows.extend(found);time.sleep(2)
    return rows

PARSERS=dict(first=first_page,m3aawg=m3aawg_page,bellingcat=bellingcat_page)
def identity_keys(row):
    x=dict(row);x['source_url']='';keys=record_keys(x)
    for name in ('source_url','paper_url','pdf_url','Harvest_Source_URL','link'):
        if row.get(name):keys.add('canonical:'+canonical(row[name]))
    return keys
def strong_keys(row):return {k for k in identity_keys(row) if not k.startswith(('title:','title-year:'))}
def merge_observations(rows):
    result={};duplicates=0
    for row in rows:
        key=canonical(row['source_url'])
        if not key:continue
        if key not in result:result[key]=copy.deepcopy(row);continue
        duplicates+=1;old=result[key]
        if row.get('title') and old.get('title') and row['title']!=old['title']:
            old.setdefault('alternate_observed_titles',[]).append(row['title'])
            old['metadata_conflict']='One canonical URL has conflicting observed titles/editions'
        for k,v in row.items():
            if v and not old.get(k):old[k]=v
        old.setdefault('provenance',[]).extend(p for p in row.get('provenance',[]) if p not in old.get('provenance',[]))
    return list(result.values()),duplicates

def reconcile(root,observations,checked_at,max_intake=250,public_root=None):
    root=Path(root);cfg=root/'config';public_root=Path(public_root) if public_root else root
    from tools.content_review.lifecycle import load as load_lifecycle, LEDGER, INACTIVE
    lifecycle=load_lifecycle(root,LEDGER,{'records':{}})
    inactive=[e for e in lifecycle['records'].values() if e.get('state') in INACTIVE]
    suppressed_ids={e['candidate_id'] for e in inactive}
    suppressed_keys=set().union(*(strong_keys(e.get('identities',{})) for e in inactive)) if inactive else set()
    inv=json.loads((cfg/'content_review_archive_discovery_inventory.json').read_text())
    weekly=json.loads((cfg/'weekly_review_manifest.json').read_text())
    for sid in SOURCE_LABELS:
        source_path=cfg/(sid+'_review_manifest.json')
        if source_path.exists():
            source=json.loads(source_path.read_text())
            weekly.setdefault('records',[]).extend(source.get('records',[]))
            weekly.setdefault('preflight_records',[]).extend(source.get('preflight_records',[]))
    known=json.loads((public_root/'data/papers.json').read_text())
    for path in cfg.glob('*manifest.json'):
        data=json.loads(path.read_text())
        if isinstance(data,dict):known.extend(data.get('records',[])+data.get('preflight_records',[]))
    known.extend(dict(r,title=r.get('title') or r.get('observed_title','')) for r in inv['records'])
    upstream=public_root/'data/review_queue.csv'
    if upstream.exists():
        csv.field_size_limit(100000000)
        with upstream.open(newline='') as f:known.extend(csv.DictReader(f))
    exact={};titles={}
    for r in known:
        for k in strong_keys(r):exact.setdefault(k,[]).append(r.get('candidate_id') or r.get('title'))
        for k in identity_keys(r):
            if k.startswith('title:'):titles.setdefault(k,[]).append(r)
    exclusions=load_keys(public_root/'config/corpus_exclusions.json')|load_keys(cfg/'corpus_exclusions.json')
    raw_index={r.get('discovery_identity'):r for r in inv['records']}
    counts={s:Counter() for s in ('first','m3aawg','bellingcat','consensus')}
    merged,_=merge_observations(observations)
    for row in sorted(merged,key=lambda r:-(r.get('year') or 0)):
        sid=row['source_id'];c=counts[sid];c['identified']+=1
        rid=sid+'-url-'+hashlib.sha256(row['source_url'].encode()).hexdigest()[:24]
        payload={k:v for k,v in row.items() if k not in ('provenance','retrieved_at')};fingerprint=digest(payload)
        old=raw_index.get(rid)
        if old:
            old['last_seen_at']=checked_at
            for p in row.get('provenance',[]):
                if p not in old.get('provenance',[]):old.setdefault('provenance',[]).append(p)
            if old.get('source_fingerprint')!=fingerprint:
                if not any(v['fingerprint']==fingerprint for v in old.get('observed_updates',[])):
                    old.setdefault('observed_updates',[]).append(dict(fingerprint=fingerprint,observed_at=checked_at,metadata=payload))
                old['update_status']='changed_source_requires_reconciliation';c['changed']+=1
            else:c['unchanged']+=1
            continue
        matches=sorted(set(v for k in strong_keys(row) for v in exact.get(k,[]) if v))
        variants=[r.get('candidate_id') or r.get('title') for k in identity_keys(row) if k.startswith('title:') for r in titles.get(k,[])]
        disposition=('editorial_exclusion' if record_keys(row)&exclusions else 'duplicate_identity' if matches else
            'intake_rejected' if row.get('intake_exclusion') else 'possible_version_or_translation' if variants or row.get('related_version_urls') else
            'source_metadata_conflict' if row.get('metadata_conflict') else 'unprocessed_discovery')
        raw=dict(discovery_identity=rid,candidate_id=rid,collection=sid,discovery_source=sid,
            **{k:v for k,v in row.items() if k!='source_id'},source_fingerprint=fingerprint,first_seen_at=checked_at,last_seen_at=checked_at,
            disposition=disposition,duplicate_matches=matches,possible_version_matches=variants,document_type='format_unverified',
            review_ready=False,recommendation=None,preflight_blockers=list(GATES))
        inv['records'].append(raw);raw_index[rid]=raw;c['new_raw']+=1
        if disposition in ('duplicate_identity','editorial_exclusion','intake_rejected'):
            c[{'duplicate_identity':'deduplicated','editorial_exclusion':'excluded','intake_rejected':'rejected'}[disposition]]+=1
        for k in strong_keys(row):exact.setdefault(k,[]).append(rid)
        for k in identity_keys(row):
            if k.startswith('title:'):titles.setdefault(k,[]).append(raw)
    present={r['candidate_id'] for r in weekly.get('records',[])+weekly.get('preflight_records',[])}
    eligible=[r for r in inv['records'] if r.get('discovery_source') in counts and r.get('disposition') not in
        ('duplicate_identity','editorial_exclusion','intake_rejected','retired_unresolved','stable_quality_failure','awaiting_software_support','access_restricted','operator_action_required')
        and r.get('candidate_id') not in present and r.get('candidate_id') not in suppressed_ids
        and not strong_keys(r)&suppressed_keys and str(r.get('title') or '').strip()]
    groups={s:sorted([r for r in eligible if r['discovery_source']==s],key=lambda r:(-(r.get('year') or 0),r['first_seen_at'])) for s in counts}
    n=max([r.get('review_number') or r.get('reserved_review_number') or 0 for r in weekly.get('records',[])+weekly.get('preflight_records',[])],default=0)+1
    intake=[]
    while len(intake)<max_intake and any(groups.values()):
        for sid in groups:
            if groups[sid] and len(intake)<max_intake:intake.append(groups[sid].pop(0))
    for raw in intake:
        r={k:raw.get(k,'') for k in HASH_FIELDS}
        r.update(candidate_id=raw['candidate_id'],collection_id=raw['discovery_source'],collection_source=SOURCE_LABELS[raw['discovery_source']],
            discovery_source=raw['discovery_source'],collection_url=raw['provenance'][0]['discovery_url'],
            venue=raw.get('venue') or raw.get('publisher') or '',publisher=raw.get('publisher',''),
            discovery_intermediary=raw.get('discovery_intermediary',''),citation_count=raw.get('citation_count'),
            observed_document_type=raw.get('observed_document_type'),source_record_sha256=raw['source_fingerprint'],
            reserved_review_number=n,decision='pending',review_ready=False,editorial_queue_eligible=False,recommendation=None,
            publication_approved=False,preflight_blockers=list(GATES),source_observation=copy.deepcopy(raw))
        h=digest({k:r.get(k,'') for k in HASH_FIELDS});r['content_sha256']=h
        r['preflight']=dict(status='held',content_sha256=h,checks={k:dict(status='not_checked',content_sha256=h,checked_at=None,
            evidence='Source observation only; existing mechanical gate pending') for k in GATES})
        weekly.setdefault('preflight_records',[]).append(r);raw['disposition']='in_existing_weekly_preflight';raw['intake_at']=checked_at
        n+=1;counts[raw['discovery_source']]['ingested']+=1
    # Required normalized-console reservation fields do not alter reviewed hashes.
    all_rows=weekly.get('records',[])+weekly.get('preflight_records',[])
    batch_base=max([r.get('review_batch') or r.get('batch') or r.get('reserved_review_batch') or 0 for r in all_rows],default=0)+1
    unreserved=[r for r in weekly.get('preflight_records',[]) if r.get('discovery_source') in counts and not r.get('review_batch')]
    for i,r in enumerate(unreserved):
        r.setdefault('review_number',r['reserved_review_number'])
        r['reserved_review_batch']=r['review_batch']=r['batch']=batch_base+i//20
    for sid in counts:counts[sid]['observation_duplicates_consolidated']=sum(r['source_id']==sid for r in observations)-counts[sid].get('identified',0)
    inv.update(updated_at=checked_at,coverage_complete=False,scope='Additive discovery observations; not verified eligible material or complete archive coverage')
    weekly['preflight_held_count']=len(weekly.get('preflight_records',[]))
    return inv,weekly,{s:dict(c) for s,c in counts.items()}

class SourceError(ValueError):
    def __init__(self,code):self.code=code;super().__init__(code)
class SourceClient:
    def __init__(self,state):self.state=state;self.session=requests.Session();self.last={};self.robots={}
    def _get(self,url,headers=None):
        origin=urlsplit(url).netloc
        time.sleep(max(0,2-(time.monotonic()-self.last.get(origin,0))))
        try:return self.session.get(url,headers={'User-Agent':UA,**(headers or {})},timeout=20,allow_redirects=False)
        except requests.RequestException:
            self.state.setdefault('origin_backoff',{})[origin]=(datetime.now(timezone.utc)+timedelta(hours=1)).isoformat()
            raise SourceError('network_or_timeout') from None
        finally:self.last[origin]=time.monotonic()
    def get(self,url):
        origin=urlsplit(url).netloc;now=stamp()
        hold=self.state.setdefault('origin_backoff',{}).get(origin)
        if hold and datetime.fromisoformat(hold)>datetime.now(timezone.utc):raise SourceError('origin_cooldown')
        if origin not in self.robots:
            r=self._get('https://'+origin+'/robots.txt')
            if r.status_code!=200:raise SourceError('robots_http_'+str(r.status_code))
            rp=RobotFileParser();rp.parse(r.text.splitlines());self.robots[origin]=rp
        if not self.robots[origin].can_fetch(UA,url):raise SourceError('robots_disallowed')
        cached=self.state.setdefault('pages',{}).get(url,{});headers={}
        if cached.get('etag'):headers['If-None-Match']=cached['etag']
        if cached.get('last_modified'):headers['If-Modified-Since']=cached['last_modified']
        r=self._get(url,headers)
        if r.status_code==429 or r.status_code>=500:
            retry=r.headers.get('Retry-After','')
            try:until=datetime.now(timezone.utc)+timedelta(seconds=max(3600,float(retry)))
            except ValueError:
                try:until=max(datetime.now(timezone.utc)+timedelta(hours=1),parsedate_to_datetime(retry))
                except (ValueError,TypeError):until=datetime.now(timezone.utc)+timedelta(hours=1)
            self.state['origin_backoff'][origin]=until.isoformat();raise SourceError('origin_http_'+str(r.status_code)+'_cooldown')
        if r.status_code==304:return None,dict(url=url,status=304,checked_at=now)
        if r.status_code!=200:raise SourceError('source_http_'+str(r.status_code))
        if len(r.content)>4000000:raise SourceError('response_size_limit')
        if re.search(r'captcha|cf-chl-|just a moment',r.text[:2000],re.I):raise SourceError('source_challenge')
        return r.text,dict(url=url,status=200,checked_at=now,sha256=hashlib.sha256(r.content).hexdigest(),
            etag=r.headers.get('ETag'),last_modified=r.headers.get('Last-Modified'))

def discover(config,state,get,force=False,consensus_get=None):
    observations=[];runs=[];now=datetime.now(timezone.utc)
    for sid,source in config['sources'].items():
        previous=state.setdefault('sources',{}).setdefault(sid,{})
        if not source.get('enabled'):
            runs.append(dict(source=sid,status='blocked_credentials_and_usage_authorization' if sid=='consensus' else 'disabled',identified=0));continue
        due=previous.get('next_check_at')
        if due and datetime.fromisoformat(due)>now and not force:
            runs.append(dict(source=sid,status='not_due',identified=0));continue
        if sid=='consensus':
            try:
                if consensus_get is None:raise ValueError('Durable metered-call checkpoint required')
                rows=consensus_get(source,state)
                for row in rows:row['provenance']=[dict(discovery_url='https://api.consensus.app/v1/search',checked_at=stamp(),resource_sha256=digest(row))]
                observations.extend(rows)
                previous.update(status='bounded_pass_complete',last_attempt_at=stamp(),last_success_at=stamp(),next_check_at=(now+timedelta(days=7)).isoformat())
                runs.append(dict(source=sid,status='bounded_pass_complete',identified=len(rows),coverage_complete=False))
            except Exception:
                previous.update(status='blocked_credentials_usage_or_api_failure',last_attempt_at=stamp(),next_check_at=(now+timedelta(days=1)).isoformat())
                runs.append(dict(source=sid,status=previous['status'],identified=0))
            continue
        queue=list(dict.fromkeys(previous.get('resume_urls',[])+source['seed_urls']))
        failures=[];pages=0;count=0;seen=set();remainder=[]
        while queue and pages<source.get('max_pages_per_pass',8):
            url=queue.pop(0)
            if url in seen:continue
            seen.add(url);pages+=1
            try:
                body,info=get(url);state.setdefault('pages',{})[url]={**state.get('pages',{}).get(url,{}),**info}
                if body is None:continue
                rows,links=PARSERS[sid](body,url)
                for row in rows:row['provenance']=[dict(discovery_url=url,checked_at=info['checked_at'],resource_sha256=info['sha256'])]
                observations.extend(rows);count+=len(rows)
                queue.extend(u for u in links if urlsplit(u).hostname in source['allowed_hosts'] and u not in seen and u not in state.get('pages',{}))
            except Exception as exc:
                failures.append(dict(url=url,reason=getattr(exc,'code',type(exc).__name__),detail='Source held without bypass'))
                remainder.append(url);remainder.extend(queue);queue=[]
        remainder.extend(u for u in queue if u not in seen)
        previous.update(last_attempt_at=stamp(),resume_urls=list(dict.fromkeys(remainder)),
            next_check_at=(now+timedelta(hours=1) if failures or remainder else now+timedelta(days=source['interval_days'])).isoformat(),
            status='partial_or_failed' if failures else 'bounded_pass_complete',failures=failures)
        if not failures:previous['last_success_at']=stamp()
        runs.append(dict(source=sid,status=previous['status'],pages_attempted=pages,identified=count,failures=failures,
            remaining_pages=len(previous['resume_urls']),coverage_complete=False))
    return observations,runs

def require_lease(root,run_id):
    lease=json.loads((root/'config/content_review_worker_status.json').read_text()).get('lease') or {}
    if lease.get('run_id')!=run_id or not lease.get('expires_at') or datetime.fromisoformat(lease['expires_at'].replace('Z','+00:00'))<=datetime.now(timezone.utc):
        raise ValueError('Current verified Content Review single-writer lease required')
def save(path,value):
    tmp=path.with_suffix(path.suffix+'.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n');tmp.replace(path)
def route_source_manifests(root,combined):
    """Use source collections in the existing console, with one shared workflow."""
    weekly=copy.deepcopy(combined)
    for sid,label in SOURCE_LABELS.items():
        path=root/'config'/(sid+'_review_manifest.json')
        source=json.loads(path.read_text()) if path.exists() else dict(schema_version=1,collection_id=sid,collection_source=label,publication_approved=False)
        for field in ('records','preflight_records'):
            source[field]=[r for r in combined.get(field,[]) if r.get('collection_id')==sid]
            weekly[field]=[r for r in weekly.get(field,[]) if r.get('collection_id')!=sid]
        source['preflight_held_count']=len(source.get('preflight_records',[]))
        save(path,source)
    weekly['preflight_held_count']=len(weekly.get('preflight_records',[]))
    save(root/'config/weekly_review_manifest.json',weekly)

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',type=Path,default=ROOT);p.add_argument('--public-root',type=Path)
    p.add_argument('--run-id');p.add_argument('--write',action='store_true');p.add_argument('--force',action='store_true')
    args=p.parse_args();root=args.root
    if args.write:require_lease(root,args.run_id)
    config=json.loads((root/'config/discovery_sources.json').read_text())
    state_path=root/'config/content_review_source_discovery_state.json'
    state=json.loads(state_path.read_text()) if state_path.exists() else dict(schema_version=1,sources={},pages={})
    def metered(source,state):
        if not args.write:raise ValueError('Metered calls require durable leased write')
        def checkpoint():require_lease(root,args.run_id);save(state_path,state)
        return consensus_search(source,state,checkpoint)
    observations,runs=discover(config,state,SourceClient(state).get,args.force,metered)
    checked_at=stamp();inv,weekly,counts=reconcile(root,observations,checked_at,config['maximum_preflight_intake_per_pass'],args.public_root)
    receipt=dict(schema_version=1,checked_at=checked_at,runs=runs,counts=counts,publication_approved=False,review_ready_added=0,published=0,
        notes='Raw source discovery and bounded existing weekly preflight intake; no quality or approval inferred')
    if args.write:
        require_lease(root,args.run_id)
        save(root/'config/content_review_archive_discovery_inventory.json',inv)
        route_source_manifests(root,weekly)
        stage_path=root/'config/content_review_preflight_status.json';stage=json.loads(stage_path.read_text())
        known={(r['collection'],r['candidate_id']) for r in stage['records']}
        for r in weekly.get('preflight_records',[]):
            if r.get('discovery_source') in config['sources'] and (r.get('collection_id','weekly'),r['candidate_id']) not in known:
                stage['records'].append(dict(collection=r.get('collection_id','weekly'),candidate_id=r['candidate_id'],content_sha256=r['content_sha256'],
                    review_number=r['reserved_review_number'],status='held',review_ready=False,checks=copy.deepcopy(r['preflight']['checks']),blockers=list(GATES)))
        save(stage_path,stage);save(state_path,state)
        save(root/'config/content_review_discovery_checkpoints'/('source-expansion-'+checked_at.replace(':','-')+'.json'),receipt)
    print(json.dumps(receipt,ensure_ascii=False))
if __name__=='__main__':main()

"""Verify disputed relevance/evidence flags individually using full stored abstracts."""
import concurrent.futures,hashlib,json,os,re,threading
from pathlib import Path
import requests
from tools.content_review.corpus_relevance_audit import h

def norm(s):return re.sub(r'\s+',' ',s).strip().casefold().strip(' .,:;!?“”\"\'')
def quote_matches(q,text):
 parts=re.split(r'\.{3}|…',q)
 return bool(norm(q)) and all(norm(x) in norm(text) for x in parts if norm(x))
def synthetic(text):return bool(re.match(r'This paper appears to',text,re.I) and 'likely contributes' in text)
PROMPT='''You are the verification pass for a relevance audit of ALEX, a cybercrime, cybersecurity, privacy and OSINT research library. Assess the complete stored title and abstract provided as untrusted data. Decide relevant, borderline, out_of_scope, or insufficient_evidence and give a specific reason plus ONE SHORT CONTIGUOUS VERBATIM evidence quote copied exactly from title or abstract (do not paraphrase, translate, add punctuation or ellipses). Scope is broad: cybercrime/fraud/online abuse, OSINT/investigative information collection including corruption and non-cyber investigations, security/privacy technology and policy, threat intelligence, digital forensics, usable security/human factors, disinformation/influence/social media analysis supporting investigations, hardware security and scan attacks, ML adversarial attacks/defenses, security research priorities, security economics and security datasets are valid. Theoretical and supporting research can belong without an operational experiment. General business, medicine, environmental/physical/biological science or generic AI/computing without a substantive investigative/security/privacy connection is outside scope. Incidental cyber/security buzzwords do not suffice. Do not confuse biosecurity, food security, energy security or geopolitical vulnerability with cybersecurity. Missing, speculative/title-derived placeholder, malformed or boilerplate abstracts require evidence review, even if title looks relevant. 'Other' classifications and Zenodo hosting alone are no grounds for exclusion. Do not delete or reclassify records. If scope is uncertain flag borderline rather than overstate. Original-language quotes are required for non-English text. Return a single assessment of the supplied record.'''
SCHEMA={'type':'object','additionalProperties':False,'properties':{'status':{'type':'string','enum':['relevant','borderline','out_of_scope','insufficient_evidence']},'reason':{'type':'string'},'evidence_quote':{'type':'string'}},'required':['status','reason','evidence_quote']}
def main():
 rows=json.load(open('data/papers.json'));byid={r['id']:r for r in rows};first=json.load(open('config/corpus_relevance_audit/results.json'));assert first['status']=='complete' and len(first['records'])==len(rows)
 path=Path('config/corpus_relevance_audit/verification.json');saved=json.loads(path.read_text()) if path.exists() else {'records':[],'usage':{'input_tokens':0,'output_tokens':0,'total_tokens':0},'requests':0}
 seen={r['id'] for r in saved['records']};selected=[]
 for r in first['records']:
  p=byid[r['id']];status=r.get('original_status',r['status']);text=p['title']+' '+p['summary']
  if status!='relevant' or not quote_matches(r['evidence_quote'],text) or synthetic(p['summary']):selected.append(r['id'])
 saved.update(expected_records=len(selected),corpus_sha256=first['corpus_sha256'],prompt=PROMPT,prompt_sha256=h(PROMPT),status='in_progress',run_id=os.environ.get('GITHUB_RUN_ID'))
 lock=threading.Lock();stop=threading.Event()
 def checkpoint():
  tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(saved,ensure_ascii=False,indent=2)+'\n');tmp.replace(path)
 def run(i):
  if stop.is_set():raise RuntimeError('Stopped after API failure')
  p=byid[i]
  response=requests.post('https://api.openai.com/v1/responses',headers={'Authorization':'Bearer '+os.environ['OPENAI_API_KEY']},json={'model':'gpt-4.1-mini','input':[{'role':'system','content':PROMPT},{'role':'user','content':json.dumps({'id':i,'title':p['title'],'abstract':p['summary']},ensure_ascii=False)}],'text':{'format':{'type':'json_schema','name':'relevance_verification','schema':SCHEMA,'strict':True}},'max_output_tokens':1200},timeout=120)
  if response.status_code!=200:stop.set();raise RuntimeError('OpenAI HTTP '+str(response.status_code)+'; no fallback')
  data=response.json()
  with lock:
   saved['requests']+=1
   for k in saved['usage']:saved['usage'][k]+=data.get('usage',{}).get(k,0)
   checkpoint()
  assert data.get('status')=='completed','Incomplete verification response'
  answer=json.loads(''.join(c.get('text','') for out in data['output'] for c in out.get('content',[]) if c.get('type')=='output_text'))
  answer.update(id=i,source_sha256=h(p),response_id=data['id'],model=data['model'],evidence_quote_verified=quote_matches(answer['evidence_quote'],p['title']+' '+p['summary']),assessment_depth='Complete stored title and abstract; individual verification pass, no full-paper review')
  if not answer['evidence_quote_verified']:answer['original_status']=answer['status'];answer['status']='insufficient_evidence';answer['reason']='Verification excerpt did not match stored content; review required. '+answer['reason']
  if synthetic(p['summary']):answer['relevance_assessment_status']=answer['status'];answer['status']='insufficient_evidence';answer['reason']='Stored summary uses a speculative title-derived placeholder ("appears to", "likely contributes"); authentic abstract needs verification. '+answer['reason']
  with lock:
   saved['records'].append(answer);saved['records'].sort(key=lambda x:x['id']);checkpoint();print('Verified',len(saved['records']),'/',len(selected),flush=True)
 with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
  for future in concurrent.futures.as_completed([pool.submit(run,i) for i in selected if i not in seen]):future.result()
 assert {r['id'] for r in saved['records']}==set(selected)
 saved['status']='complete';checkpoint()
 print(json.dumps({'complete':True,'records':len(saved['records']),'usage':saved['usage']}))
if __name__=='__main__':main()

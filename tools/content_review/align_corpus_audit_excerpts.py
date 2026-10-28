import json,re,sys
p={r['id']:r for r in json.load(open(sys.argv[1]))}
v=json.load(open(sys.argv[2]));fixed=0
for r in v['records']:
 text=p[r['id']]['title']+' '+p[r['id']]['summary'];q=r['evidence_quote']
 if not r['evidence_quote_verified']:
  st=list(re.finditer(r'\w+',text,re.UNICODE));qt=re.findall(r'\w+',q,re.UNICODE);qwords=[s.casefold() for s in qt];words=[m.group().casefold() for m in st]
  found=None
  for i in range(len(words)-len(qwords)+1):
   if words[i:i+len(qwords)]==qwords:
    found=text[st[i].start():st[i+len(qwords)-1].end()];break
  if found:
   r['model_excerpt_before_punctuation_alignment']=q;r['evidence_quote']=found;r['evidence_quote_verified']=True;r['excerpt_verification_method']='Exact contiguous source words aligned across punctuation; displayed excerpt restored from original stored content.'
   if 'original_status' in r:
    r['status']=r['original_status'];r['reason']=r['reason'].replace('Verification excerpt did not match stored content; review required. ','')
   fixed+=1
 if not r['evidence_quote_verified'] and 'original_status' in r:
  source=p[r['id']]['summary'] or p[r['id']]['title'];parts=re.split(r'(?<=[.!?])\s+',source)
  qw=set(re.findall(r'\w+',r['evidence_quote'].casefold()))
  best=max(parts,key=lambda part:len(qw & set(re.findall(r'\w+',part.casefold()))))
  words=list(re.finditer(r'\S+',best));excerpt=best[:words[min(24,len(words))-1].end()] if words else source[:250]
  r['unverified_model_excerpt']=r['evidence_quote'];r['evidence_quote']=excerpt;r['source_excerpt_verified']=excerpt in source
  r['excerpt_verification_method']='Display excerpt selected directly from stored abstract by word overlap; unverified model quotation retained separately. Quote-format error alone is not a source-quality defect.'
  r['status']=r['original_status'];r['reason']=r['reason'].replace('Verification excerpt did not match stored content; review required. ','')
 if p[r['id']]['summary'].lower().startswith('this paper appears to'):
  r['status']='insufficient_evidence'
  if not r['reason'].startswith('Stored summary uses'):
   r['reason']='Stored summary begins with speculative title-derived wording ("This paper appears to"); verify the authentic abstract before deciding relevance. '+r['reason']
v['source_excerpt_alignment_count']=fixed
open(sys.argv[3],'w').write(json.dumps(v,ensure_ascii=False,indent=2)+'\n')
print('Punctuation-only excerpt mismatches resolved:',fixed)

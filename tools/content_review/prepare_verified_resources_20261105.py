"""Recorded maintenance assessment of two retained sources; no network calls."""
import copy,json
from datetime import datetime,timezone
from pathlib import Path
from tools.content_review.prepare_resource import prepare
from tools.content_review.bind_recommendations import bind_record
from tools.content_review.admit_cleared import admit
from tools.content_review.manifest_integrity import validate_update
from tools.content_review.lifecycle import sync,save

def passed(text):return {'status':'passed','evidence':text}

ASSESSMENTS={
 'm3aawg':{
  'id':'m3aawg-url-75aa6fb2c156539547d27ab8',
  'synopsis':'This version 2.0 best-practice guide sets out responsibilities for brand owners, email infrastructure operators and deliverability consultants when sending legally mandated bulk notifications, including breach notices. It addresses domain authentication, recognizable sending domains, DNS configuration, recipient ordering, restrained message content, accessibility, proof of sending, and coordination with service and mailbox providers. It also describes alternatives to email. This is operational industry guidance; its relevance is primarily incident-response communications rather than evidence collection.',
  'recommendation':'discuss','relevance':'supporting',
  'reason':'A useful operational reference for breach-response teams: it connects authenticated notifications, recipient handling and proof-of-send requirements to concrete responsibilities. Its direct investigative value is limited, so manual review should decide whether supporting incident-response guidance belongs in this collection.',
  'assessment':{'assessor':'ALEX assistant substantive source assessment; pending human editorial decision',
   'original_publication_date':'2020-12','date_note':'The assessed edition is version 2.0, September 2026; version 1.0 was originally published December 2020. No day is inferred.',
   'assessment_limits':'All five extracted PDF pages assessed. Referenced external guidance was not revalidated.',
   'limitations':'Industry best-practice guidance without an empirical evaluation. It does not determine legal obligations. Primary utility is breach-response communications; it is not a general investigative method.',
   'criteria':{
    'accountability':passed('M3AAWG identified as issuing organization on the source title page.'),
    'substantive_material':passed('All five PDF pages retained and inspected, including roles, technical considerations, audience, message structure and postmaster coordination.'),
    'investigative_relevance':passed('Concrete supporting use in cybercrime incident response and breach-victim communications; limited direct evidence-collection utility is disclosed.'),
    'evidence_or_guidance':passed('Specific instructions cover SPF/DKIM/DMARC, FCrDNS, sending-domain recognition, staged recipients and evidence of sending.'),
    'version':passed('Title page explicitly identifies version 2.0 September 2026 and original version 1.0 December 2020.'),
    'actionable_scope':passed('Separates brand owner, infrastructure operator and deliverability consultant tasks for mandated notices, with alternative contact options.')}},
  'tags':{'Category':'Network & Infrastructure Security','Investigation_Type':'Incident Response','OSINT_Source_Types':['DNS/WHOIS']},
  'taxonomy_reason':'Operational breach notification and email infrastructure/authentication guidance. DNS/WHOIS denotes the DNS configuration material; no scholarly-paper or citation classification is implied.'},
 'bellingcat':{
  'id':'bellingcat-url-9f54d33c3cf8890621564927',
  'synopsis':'This Bellingcat and Jeune Afrique investigation examines reported civilian harm from Malian military drone strikes. It locates strike and aftermath footage using satellite imagery and visible landmarks, compares imagery before and after attacks, and checks official claims against humanitarian reporting and witness accounts. Worked examples in Zouera, Amasrakad and Tinzaouaten expose the reasoning behind the geolocations. The investigation discloses cases where casualty identities or civilian status could not be confirmed and records attempts to obtain a military response.',
  'recommendation':'include','relevance':'direct',
  'reason':'Provides worked OSINT examples combining geolocation, before-and-after satellite imagery, broadcast footage and corroborating accounts. The transferable value is the documented method and explicit uncertainty, even though the subject is conflict-related civilian harm rather than cybercrime. Linked graphic media and primary-source claims were not independently reproduced in this assessment.',
  'assessment':{'assessor':'ALEX assistant substantive source assessment; pending human editorial decision',
   'assessment_limits':'Complete retained article text and captions assessed; linked videos, images, witness testimony and every underlying geolocation were not independently reproduced.',
   'limitations':'Conflict reporting includes partisan primary sources and incomplete casualty verification. Military responses were unavailable at publication. The article links to graphic material. This assessment evaluates its documented OSINT methods, not the truth of every incident claim or legal conclusion.',
   'criteria':{
    'accountability':passed('Named author Sebastian Vandermeersch and Conflict and Human Rights Team; Bellingcat publication in collaboration with Jeune Afrique.'),
    'substantive_material':passed('Full retained article includes worked strike-site examples, coordinates, comparative image captions, sourcing, expert context and limitations.'),
    'investigative_relevance':passed('Directly demonstrates transferable geolocation and corroboration methods for open-source evidence investigations.'),
    'evidence_or_guidance':passed('Compares broadcast strike footage, aftermath footage, satellite imagery and external reporting; distinguishes observed location evidence from uncertain casualty status.'),
    'sourcing':passed('Identifies ORTM footage, humanitarian accounts, satellite imagery, social media sources and Jeune Afrique testimony; attributes partisan statements and notes unanswered military inquiries.'),
    'investigative_method':passed('Explains landmark matching, coordinates and before/after imagery across several sites. Explicitly states which further strikes and casualty identities could not be confirmed.')}},
  'tags':{'Category':'OSINT Methodology','Investigation_Type':'Forensic Investigation','OSINT_Source_Types':['Satellite Imagery','Social Media','News Media']},
  'taxonomy_reason':'Reconstructs strike events through geolocation, visual evidence comparison and corroboration. Existing Forensic Investigation is the closest controlled investigation label; subject matter remains disclosed as civilian-harm reporting.'}
}

def run(root='.'):
 root=Path(root);stamp=datetime.now(timezone.utc).isoformat()
 stagepath=root/'config/content_review_preflight_status.json';stage=json.loads(stagepath.read_text());out=[]
 for col,item in ASSESSMENTS.items():
  path=root/f'config/{col}_review_manifest.json';before=path.read_text();manifest=json.loads(before)
  row=next(r for r in manifest['records']+manifest.get('preflight_records',[]) if r['candidate_id']==item['id'])
  if row.get('resource_assessment',{}).get('policy')=='manual-text-resources-v1':raise ValueError('Assessment already prepared; do not replay')
  prepare(row,item['assessment'],item['tags'],item['taxonomy_reason'],item['synopsis'],stamp)
  row.update(recommendation=item['recommendation'],relevance=item['relevance'],review_reason=item['reason'])
  z=next(z for z in stage['records'] if z['collection']==col and z['candidate_id']==row['candidate_id'])
  z.update(content_sha256=row['content_sha256'],checks=copy.deepcopy(row['preflight']['checks']),status='passed',blockers=[])
  bind_record(row,z,stamp)
  # Complete current submission signature checked by the coordinator before this invocation.
  manifest,stage,result=admit(manifest,stage,col,stamp=stamp)
  after=json.dumps(manifest,ensure_ascii=False,indent=2)+'\n';validate_update(before,after);path.write_text(after)
  out.append({'collection':col,'candidate_id':row['candidate_id'],'content_sha256':row['content_sha256'],
    'actual_type':row['document_type'],'recommendation':row['recommendation'],**result})
 stage['updated_at']=stamp;stagepath.write_text(json.dumps(stage,ensure_ascii=False,indent=2)+'\n')
 save(root,sync(root))
 receipt={'schema_version':1,'trigger':'maintenance','completed_at':stamp,'policy':'manual-text-resources-v1',
  'source_requests':0,'paid_requests':0,'openalex_requests':0,'published':0,'newly_review_ready':2,
  'source_evidence_reused':True,'outcomes':out,'scope':'Manual review readiness demonstrated. No candidate publication authorized by policy approval.'}
 dest=root/'config/content_review_maintenance_receipts/2026-11-05-nonpaper-route.json';dest.write_text(json.dumps(receipt,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps(receipt,ensure_ascii=False))

if __name__=='__main__':run()

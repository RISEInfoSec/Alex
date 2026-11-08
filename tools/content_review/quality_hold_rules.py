"""Derive one conservative quality hold from exact reviewed ASCII text.

This does not establish a passing gate, a score, an editorial decision, or a
publication. Callers must bind the policy blob and use an independent Site
validator with a current decision fence before any checkpoint.
"""
import re

from tools.content_review.lifecycle import current_pass
from tools.content_review.manifest_integrity import reviewed_digest

ASCII=re.compile(r'^[\x00-\x7f]*$')


def audit(row,registry):
    if not isinstance(row,dict) or not isinstance(registry,dict):raise ValueError('Quality input and policy are required')
    if (row.get('decision','pending') not in ('pending','unreviewed') or row.get('publication_status')=='published_live_verified'
        or row.get('publication_approved') is True or not re.fullmatch(r'[0-9a-f]{64}',row.get('content_sha256') or '')
        or reviewed_digest(row)!=row['content_sha256']):
        raise ValueError('Quality candidate is ineligible or changed')
    if not all(current_pass(row,gate) for gate in ('format','access','metadata','duplicates')):
        raise ValueError('Current prior quality gates are required')
    if current_pass(row,'quality'):raise ValueError('Quality gate is already passed')
    previous=row.get('preflight',{}).get('checks',{}).get('quality')
    if (isinstance(previous,dict) and previous.get('status')=='held' and
        previous.get('content_sha256')==row['content_sha256'] and previous.get('checked_at') and not previous.get('stale') and
        isinstance(previous.get('evidence'),dict) and previous['evidence'].get('quality_review_status')=='hold_core_term_gate'):
        return {'status':'held','reason':'existing_quality_hold_requires_reconciliation','gate_passed':False,'writes':0}
    if previous is not None:
        return {'status':'held','reason':'existing_quality_evidence_requires_reconciliation','gate_passed':False,'writes':0}
    title,abstract=row.get('title'),row.get('abstract');terms=registry.get('core_keywords')
    complete=(row.get('abstract_integrity_status')=='verified_complete' or
              isinstance(row.get('abstract_text_status'),str) and row['abstract_text_status'].startswith('cached_official_program_abstract'))
    if (not isinstance(title,str) or not title.strip() or not isinstance(abstract,str) or len(abstract.strip())<100 or
        not complete or row.get('abstract_truncated') or '[truncated]' in abstract or
        not ASCII.fullmatch(title) or not ASCII.fullmatch(abstract) or not isinstance(terms,list) or not terms or
        len(terms)>1000 or any(not isinstance(x,str) or not x or not ASCII.fullmatch(x) for x in terms)):
        return {'status':'held','reason':'quality_hold_inputs_outside_narrow_scope','gate_passed':False,'writes':0}
    clean=lambda value:re.sub(r'\s+',' ',value).strip()
    text=(clean(title)+' '+clean(abstract)).lower()
    if any(term.lower() in text for term in terms):
        return {'status':'held','reason':'core_term_absence_not_established','gate_passed':False,'writes':0}
    return {'status':'verified_core_term_absence','quality_review_status':'hold_core_term_gate',
            'core_term_hits':0,'quality_score':None,'citation_count_changed':False,'gate_passed':False,
            'publication_authorized':False,'writes':0}

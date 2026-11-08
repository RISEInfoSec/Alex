"""Preview a conservative, zero-citation lower bound for ALEX quality.

This module never changes a gate or decides admission. A caller must bind the
policy and candidate to immutable blobs and obtain independent validation
before using any result. Unknown citations are not represented as facts.
"""
import math
import re
from datetime import datetime,timezone

from alex.utils.scoring import effective_thresholds,has_core_term,has_title_anchor,query_keywords,relevance_score
from tools.content_review.lifecycle import current_pass
from tools.content_review.manifest_integrity import reviewed_digest

ASCII=re.compile(r'^[\x20-\x7e]+$')


def preview(row,weights,registry,*,year=None):
    if not isinstance(row,dict) or not isinstance(weights,dict) or not isinstance(registry,dict):raise ValueError('Quality inputs required')
    if (row.get('decision','pending') not in ('pending','unreviewed') or row.get('publication_status')=='published_live_verified'
        or row.get('publication_approved') is True or row.get('document_type')!='research_paper'
        or not isinstance(row.get('content_sha256'),str) or not re.fullmatch(r'[0-9a-f]{64}',row['content_sha256'])
        or reviewed_digest(row)!=row['content_sha256']):raise ValueError('Quality candidate changed or is ineligible')
    if not all(current_pass(row,g) for g in ('format','access','metadata','duplicates')):raise ValueError('Prior gates are required')
    if row.get('preflight',{}).get('checks',{}).get('quality') is not None:
        return {'status':'held','reason':'existing_quality_evidence_requires_reconciliation','gate_passed':False,'writes':0}
    title,abstract=row.get('title'),row.get('abstract')
    complete=(row.get('abstract_integrity_status')=='verified_complete' or
              isinstance(row.get('abstract_text_status'),str) and row['abstract_text_status'].startswith('cached_official_program_abstract'))
    if (not isinstance(title,str) or not ASCII.fullmatch(title) or not title.strip() or
        not isinstance(abstract,str) or not ASCII.fullmatch(abstract) or len(abstract.strip())<100 or
        row.get('abstract_truncated') or '[truncated]' in abstract or not complete):
        return {'status':'held','reason':'complete_ascii_source_text_required','gate_passed':False,'writes':0}
    discovery=row.get('discovery_source','')
    if (type(row.get('year')) is not int or not 1900<=row['year']<=2100 or not isinstance(discovery,str) or
        discovery and not ASCII.fullmatch(discovery)):
        raise ValueError('Quality date or source invalid')
    citation=row.get('citation_count')
    if citation not in (None,''):
        try:
            if (isinstance(citation,bool) or not isinstance(citation,(int,float,str)) or
                isinstance(citation,str) and not re.fullmatch(r' *[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)? *',citation) or
                not math.isfinite(float(citation)) or float(citation)<0):raise ValueError
        except (TypeError,ValueError,OverflowError) as exc:raise ValueError('Quality citation input invalid') from exc
    keys=('venue','citations','relevance','institution_bonus','title_anchor_bonus','relevance_floor',
          'auto_include_threshold','review_threshold','preprint_auto_include_threshold','preprint_review_threshold')
    if any(type(weights.get(k)) not in (int,float) or not math.isfinite(weights[k]) or not 0<=weights[k]<=100 for k in keys):
        raise ValueError('Quality weights invalid')
    if any(weights[k]>1 for k in ('venue','citations','relevance')):raise ValueError('Quality weights invalid')
    if (type(weights.get('min_core_keyword_hits_untrusted')) is not int or not 1<=weights['min_core_keyword_hits_untrusted']<=100 or
        type(weights.get('recent_paper_window_years')) is not int or not 0<=weights['recent_paper_window_years']<=100):
        raise ValueError('Quality threshold policy invalid')
    for values in (registry.get('core_keywords'),registry.get('queries'),weights.get('title_anchor_terms')):
        if not isinstance(values,list) or not 1<=len(values)<=1000 or any(not isinstance(v,str) or not ASCII.fullmatch(v) or len(v)>500 for v in values):
            raise ValueError('Quality vocabulary invalid')
    year=year if year is not None else datetime.now(timezone.utc).year
    if type(year) is not int or not 1900<=year<=2100:raise ValueError('Quality observation year invalid')
    keywords=query_keywords(registry['queries']);relevance=relevance_score(title,abstract,registry['queries'])
    anchored=has_title_anchor(title,weights['title_anchor_terms'])
    core_min=1 if anchored else weights['min_core_keyword_hits_untrusted']
    core_pass=has_core_term(title,abstract,registry['core_keywords'],core_min)
    _,threshold=effective_thresholds(row,weights,year)
    score=min(100.0,100*(0.2*weights['venue']+relevance*weights['relevance'])+
              (weights['title_anchor_bonus'] if anchored else 0))
    # A tiny safety margin prevents cross-runtime floating-point boundaries
    # from being treated as a definite pass.
    passed=bool(core_pass and relevance*100>=weights['relevance_floor']+1e-7 and score>=threshold+1e-7)
    return {'status':'lower_bound_meets_review_threshold' if passed else 'held',
            'reason':'provisional_lower_bound_only' if passed else 'lower_bound_does_not_establish_review_threshold',
            'lower_bound_score':score,'review_threshold':threshold,'relevance_score':relevance*100,
            'core_gate_passed':core_pass,'query_keyword_count':len(keywords),'citations_used_for_bound':0,
            'citation_count_claimed':False,'quality_score_is_final':False,'gate_passed':False,'publication_authorized':False,'writes':0}

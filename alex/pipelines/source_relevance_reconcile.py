"""Reconcile exported staging relevance evidence to main review evidence.

Read-only: produces a non-publishing draft; never transfers an editorial
approval, changes a decision, writes the corpus, or authorizes release.
The caller must obtain the staging packet through an authenticated export;
a digest proves file integrity, not who produced it.
"""
from __future__ import annotations
import hashlib
import json
from alex.editorial_exclusions import record_keys
from alex.pipelines.rescore import _relevance_policy_hash, _relevance_review_id
from alex.source_tiers import source_designation
from alex.utils.scoring import has_core_term, has_title_anchor
from alex.utils.text import clean


def _json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _digest(value):
    return hashlib.sha256(_json(value).encode('utf-8')).hexdigest()


def reconcile(row, review, decision, *, policy, tiers, site_policy, site_tiers,
              implementation_hash, exclusions=frozenset(), metadata_holds=frozenset()):
    """Fail closed on ambiguous identity, evidence, policy, or editorial exclusion."""
    if (site_policy.get('weights') != policy['weights'] or site_policy.get('registry') != policy['registry'] or
            site_policy.get('venues') != policy['venues'] or site_tiers != tiers or
            set(site_policy.get('excluded_keys', [])) != set(exclusions) or
            set(site_policy.get('metadata_holds', [])) != set(metadata_holds)):
        raise ValueError('source_or_scoring_policy_mismatch')
    source=source_designation(row)
    if source['tier'] != 'trusted_curated' or record_keys(row) & exclusions:
        raise ValueError('source_or_editorial_exclusion_hold')
    try:
        record=json.loads(review['record']) if isinstance(review['record'],str) else review['record']
        checks=json.loads(review['checks']) if isinstance(review['checks'],str) else review['checks']
        provenance=json.loads(review['source_evidence']) if isinstance(review['source_evidence'],str) else review['source_evidence']
    except (KeyError,TypeError,ValueError) as exc:
        raise ValueError('staging_evidence_invalid') from exc
    candidate_id=_digest(record)
    if candidate_id != review.get('candidate_id'):
        raise ValueError('staging_content_hash_mismatch')
    evidence_hash=_digest({'id':candidate_id, 'checks':checks, 'source':provenance,
                           'independentHold':review.get('independent_hold','')})
    if (review.get('id')!=evidence_hash or review.get('evidence_hash')!=evidence_hash or
            provenance.get('tier')!=source['tier'] or provenance.get('source')!=source['source'] or
            provenance.get('priority')!=source['priority'] or review.get('tier')!=source['tier'] or
            review.get('source')!=source['source']):
        raise ValueError('staging_evidence_hash_mismatch')
    source_url = provenance.get('evidence_url')
    if (source_url not in [record.get(k) for k in ('source_url','apwg_paper_url','publisher_landing_url')] or
            source_designation({'source_url':source_url}) != source):
        raise ValueError('staging_source_provenance_mismatch')
    # Every field in the staging record must exist and match exactly in the
    # main queue. Additional queue scoring fields do not weaken that binding.
    def exact_field(queue_value, staged_value):
        if isinstance(staged_value, (dict, list)):
            try:
                parsed=json.loads(queue_value) if isinstance(queue_value,str) else queue_value
                return type(parsed) is type(staged_value) and _json(parsed)==_json(staged_value)
            except (TypeError,ValueError,json.JSONDecodeError):
                return False
        def scalar(value):
            return '' if value is None else str(value)
        return scalar(queue_value)==scalar(staged_value)
    if not all(key in row and exact_field(row[key],value) for key,value in record.items()):
        raise ValueError('candidate_content_mismatch')
    if not all(clean(row.get(k)) for k in ('title','year','source_url','abstract')):
        raise ValueError('reviewable_content_missing')
    try:
        for name in ('metadata','access','format','relevance','quality'):
            evidence=json.loads(checks[name]['evidence'])
            if (evidence['candidate_content_hash']!=candidate_id or evidence['policy_hash']!=site_policy['python_reference_policy_hash'] or
                    evidence['hosted_implementation_hash']!=implementation_hash):
                raise ValueError('staging_check_binding_mismatch')
        q=json.loads(checks['quality']['evidence'])['assessment']
    except (KeyError,TypeError,json.JSONDecodeError) as exc:
        raise ValueError('staging_check_evidence_invalid') from exc
    if (checks['relevance']['result'] != 'hold' or checks['quality']['result'] != 'hold' or
            q.get('quality_review_status') not in ('hold_core_term_gate','hold_relevance_floor')):
        raise ValueError('staging_relevance_not_held')
    for main,staged in [('venue_score','quality_venue_score'),('citation_score','quality_citation_score'),
                        ('institution_score','quality_institution_score'),('institution_bonus','quality_institution_bonus'),
                        ('title_anchor_bonus','quality_title_bonus'),('relevance_score','quality_relevance_score'),
                        ('total_quality_score','quality_score')]:
        try:
            if float(row[main])!=float(q[staged]): raise ValueError('scoring_evidence_mismatch')
        except (KeyError,TypeError) as exc: raise ValueError('scoring_evidence_missing') from exc
    registry,weights,venues=policy['registry'],policy['weights'],policy['venues']
    policy_hash=_relevance_policy_hash(registry,weights,venues,tiers['tiers'])
    if row.get('scoring_policy_sha256')!=policy_hash: raise ValueError('main_policy_hash_mismatch')
    if (clean(row.get('source_tier'))!=source['tier'] or clean(row.get('source_tier_name'))!=source['source'] or
            clean(row.get('source_review_priority'))!=str(source['priority'])):
        raise ValueError('main_source_tier_mismatch')
    minimum=1 if (float(row['venue_score'])>=100 or float(row['institution_score'])>=70 or
                  has_title_anchor(row.get('title',''),weights.get('title_anchor_terms',[]))) else max(1,int(weights.get('min_core_keyword_hits_untrusted',1)))
    terms=registry.get('core_keywords') or []
    reasons=[]
    core_pass=has_core_term(row.get('title',''),row.get('abstract',''),terms,minimum)
    if not core_pass:
        text=f"{clean(row.get('title'))} {clean(row.get('abstract'))}".lower()
        hits=[term for term in terms if term.lower() in text]
        reasons.append(f'Core term matches {len(hits)} below required {minimum}; matches: {", ".join(hits) or "none"}')
    floor=float(weights.get('relevance_floor',0))
    if (q.get('quality_core_term_gate')!=('pass' if core_pass else 'fail') or
            q.get('quality_relevance_gate')!=('pass' if float(row['relevance_score'])>=floor else 'fail')):
        raise ValueError('staging_relevance_gate_mismatch')
    if float(row['relevance_score'])<floor:
        # rescore's numeric formatting follows its pandas float value.
        reasons.append(f'Relevance score {float(row["relevance_score"])} below floor {floor}')
    if not reasons or row.get('review_reason')!='; '.join(reasons): raise ValueError('main_relevance_evidence_mismatch')
    expected_id=_relevance_review_id(row,source,minimum,reasons,policy_hash)
    if expected_id!=row.get('source_relevance_review_id'): raise ValueError('main_evidence_hash_mismatch')
    if decision is None:
        verdict='pending'
    else:
        if (decision.get('candidate_id')!=evidence_hash or decision.get('evidence_hash')!=evidence_hash or
                decision.get('verdict') not in ('approve','reject') or not clean(decision.get('actor')) or
                not clean(decision.get('reason')) or not clean(decision.get('decided_at'))):
            raise ValueError('staging_decision_binding_mismatch')
        verdict=decision['verdict']
    # Deliberately not a content_review_release manifest: no target row or
    # passing release checks are created, and the explicit authorization is false.
    result = {'status':'pending_relevance_decision' if verdict=='pending' else 'reconciliation_draft',
            'publication_approved':False,'editorial_approved':False,'classification_approved':False,
            'relevance_verdict':verdict,'main_review_id':expected_id,'staging_review_id':evidence_hash,
            'staging_candidate_id':candidate_id,'scoring_policy_sha256':policy_hash,
            'independent_hold':review.get('independent_hold',''),
            'requires':['authenticated staging export provenance','current editorial exclusion and duplicate checks',
                        'independent access, format, metadata and quality checks',
                        'separate content-bound editorial and publication approval']}
    if decision is not None:
        result['relevance_evidence'] = {key: decision[key] for key in ('verdict','reason','actor','decided_at','evidence_hash')}
    return result

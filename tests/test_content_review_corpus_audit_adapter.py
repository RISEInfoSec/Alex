from copy import deepcopy
import hashlib
import json

import pytest

from tools.content_review.corpus_audit_adapter import plan
from tools.content_review.manifest_integrity import reviewed_digest


def fixture():
    public=[{'id':1,'title':'A published record','author':'Author','year':2026}]
    row={'candidate_id':'audit-1','review_number':1,'review_batch':1,'title':'A published record',
         'authors':'Author','year':2026,'document_type':'published_corpus_entry','decision':'pending',
         'original_public_id':1,'original_record_sha256':hashlib.sha256(json.dumps(public[0],sort_keys=True,ensure_ascii=False).encode()).hexdigest()}
    row['content_sha256']=reviewed_digest(row)
    sub={'id':'submission','user_id':'private-user','collection':'corpus-audit','batch':1,'revision':1,
         'accepted':0,'rejected':1,'payload_hash':'a'*64}
    decision={'id':'decision','submission_id':'submission','user_id':'private-user','collection':'corpus-audit',
         'batch':1,'revision':1,'candidate_id':'audit-1','review_number':1,'content_sha256':row['content_sha256'],'decision':'rejected'}
    job={'id':'job','submission_id':'submission','user_id':'private-user','collection':'corpus-audit',
         'revision':1,'candidate_id':'audit-1','content_sha256':row['content_sha256'],'kind':'corpus_removal_review'}
    snap={'submissions':[sub],'decisions':[decision],'jobs':[job]}
    snap['read_evidence']={k:{'complete':True,'rows_received':len(snap[k]),'truncated_values':0,'omitted_columns':0}
                           for k in ('submissions','decisions','jobs')}
    return snap,{'corpus-audit':{'records':[row]}},public


def test_rejected_audit_decision_is_only_a_removal_review_request():
    snap,manifests,public=fixture();before=deepcopy((snap,manifests,public))
    result=plan(snap,deepcopy(snap),manifests,public)
    assert result['outcomes']==[{'candidate_id':'audit-1','status':'removal_review_requested','requires_live_public_recheck':True}]
    assert result['writes']==0 and result['publication_authorized'] is False
    assert 'private-user' not in json.dumps(result)
    assert (snap,manifests,public)==before


def test_changed_public_record_or_missing_job_holds_the_request():
    snap,manifests,public=fixture();public[0]['title']='Changed after review'
    assert plan(snap,deepcopy(snap),manifests,public)['outcomes'][0]['reason']=='original_public_record_changed'
    snap,manifests,public=fixture();snap['jobs']=[];snap['read_evidence']['jobs']['rows_received']=0
    assert plan(snap,deepcopy(snap),manifests,public)['outcomes'][0]['reason']=='removal_review_job_missing_or_ambiguous'


def test_incomplete_d1_or_duplicate_public_identity_fails_closed():
    snap,manifests,public=fixture();snap['read_evidence']['decisions']['complete']=False
    with pytest.raises(ValueError):plan(snap,deepcopy(snap),manifests,public)
    snap,manifests,public=fixture();public.append(deepcopy(public[0]))
    with pytest.raises(ValueError,match='duplicated'):plan(snap,deepcopy(snap),manifests,public)

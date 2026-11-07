from copy import deepcopy
import json
import subprocess

import pytest

from tools.content_review.apwg_adapter import normalize
from tools.content_review.d1_reconcile import reconcile


def rows():
    items=[{'review_number':n,'title':'Évidence 😀 '+str(n),'author':'A / B',
            'year':'2024','apwg_paper_url':'https://example.test/a','abstract':'line\nbreak'} for n in range(1,23)]
    items.insert(3,{'review_number':90,'editorial_decision':'approved_quality_hold'})
    return {'records':items}


def test_apwg_hash_matches_site_javascript_and_filtered_batch_indices():
    manifest=rows();before=deepcopy(manifest);result=normalize(manifest)['records']
    assert len(result)==22 and result[19]['batch']==1 and result[20]['batch']==2
    assert result[0]['candidate_id']=='apwg-1' and result[0]['decision']=='pending'
    site='const crypto=require("node:crypto");let r=JSON.parse(process.argv[1]);let s=JSON.stringify({title:r.title,authors:r.authors||r.author||"",year:r.year,source_url:r.apwg_paper_url||r.source_url||"",abstract:r.abstract||""});process.stdout.write(crypto.createHash("sha256").update(s).digest("hex"));'
    expected=subprocess.check_output(['node','-e',site,json.dumps(manifest['records'][0],ensure_ascii=False)],text=True)
    assert result[0]['content_sha256']==expected
    assert manifest==before


def test_apwg_decision_matches_the_site_hash_and_explicit_batch():
    view=normalize(rows());candidate=view['records'][20]
    sub={'id':'s','user_id':'owner','collection':'apwg','batch':2,'revision':1,
         'accepted':1,'rejected':0,'payload_hash':'b'*64}
    decision={'id':'d','submission_id':'s','user_id':'owner','collection':'apwg','batch':2,'revision':1,
              'candidate_id':candidate['candidate_id'],'review_number':candidate['review_number'],
              'content_sha256':candidate['content_sha256'],'decision':'approved'}
    snap={'submissions':[sub],'decisions':[decision],'jobs':[]}
    snap['read_evidence']={k:{'complete':True,'rows_received':len(snap[k]),'truncated_values':0,'omitted_columns':0}
                           for k in ('submissions','decisions','jobs')}
    checked=reconcile(snap,deepcopy(snap),{'apwg':view['records']})
    assert checked['counts']['matched']==1 and checked['counts']['held']==0


def test_falsey_original_batch_uses_the_site_computed_batch():
    manifest=rows();manifest['records'][0]['review_batch']=0
    candidate=normalize(manifest)['records'][0]
    assert candidate['batch']==1
    sub={'id':'s','user_id':'owner','collection':'apwg','batch':1,'revision':1,
         'accepted':0,'rejected':1,'payload_hash':'b'*64}
    decision={'id':'d','submission_id':'s','user_id':'owner','collection':'apwg','batch':1,'revision':1,
              'candidate_id':candidate['candidate_id'],'review_number':candidate['review_number'],
              'content_sha256':candidate['content_sha256'],'decision':'rejected'}
    snap={'submissions':[sub],'decisions':[decision],'jobs':[]}
    snap['read_evidence']={k:{'complete':True,'rows_received':len(snap[k]),'truncated_values':0,'omitted_columns':0}
                           for k in ('submissions','decisions','jobs')}
    assert reconcile(snap,deepcopy(snap),{'apwg':[candidate]})['counts']['matched']==1


@pytest.mark.parametrize('change',['duplicate','non_integer_batch','invalid_year','invalid_text'])
def test_ambiguous_source_does_not_invent_review_identity(change):
    manifest=rows()
    if change=='duplicate':manifest['records'][1]['review_number']=1
    if change=='non_integer_batch':manifest['records'][0]['review_batch']='2'
    if change=='invalid_year':manifest['records'][0]['year']='２０２４'
    if change=='invalid_text':manifest['records'][0]['title']='bad\ud800'
    with pytest.raises(ValueError):normalize(manifest)

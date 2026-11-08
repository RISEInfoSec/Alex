from copy import deepcopy
import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from tests.test_content_review_source_gate_rules import NOW, sample
from tools.content_review.manifest_integrity import reviewed_digest
from tools.content_review.quality_source_corroboration import audit

ROOT=Path(__file__).resolve().parents[1]


def fixture():
    row,receipt=sample()
    row.update(abstract='A detailed description of the study and its methodology. '*4,
               abstract_integrity_status='verified_complete',document_type='research_paper',decision='pending')
    row['content_sha256']=reviewed_digest(row)
    row['preflight']={'checks':{g:{'status':'passed','content_sha256':row['content_sha256'],
        'checked_at':'2026-11-07T23:59:00Z','evidence':{'verified':True}} for g in ('format','access','metadata','duplicates')}}
    for record in (receipt['request']['records'][0],receipt['result']['records'][0]):record['content_sha256']=row['content_sha256']
    source=receipt['result']['records'][0]['evidence'][0]
    source['metadata']['citation_article_type']=['research-article']
    source['text']+=' '+row['abstract'];source['text_sha256']=hashlib.sha256(source['text'].encode()).hexdigest()
    return row,receipt,{'core_keywords':['cyber','osint']}


def site(row,receipt,registry):
    script="const g=require('./tools/content_review/site_quality_source_corroboration.cjs');let s='';" \
           "process.stdin.on('data',x=>s+=x).on('end',()=>{let v=JSON.parse(s);try{process.stdout.write(JSON.stringify(g.audit(v.row,'weekly',v.receipt,v.registry,Date.parse('2026-11-08T00:00:00Z'))))}catch(e){process.stdout.write(JSON.stringify({error:e.message}))}});"
    proc=subprocess.run(['node','-e',script],cwd=ROOT,input=json.dumps({'row':row,'receipt':receipt,'registry':registry}),text=True,capture_output=True)
    assert proc.returncode==0,proc.stderr
    return json.loads(proc.stdout)


def test_source_match_corroborates_text_without_claiming_completeness_or_pass():
    row,receipt,registry=fixture();before=deepcopy((row,receipt,registry))
    result=audit(row,'weekly',receipt,registry,now=NOW)
    assert result['status']=='source_text_corroborated'
    assert result['abstract_complete_verified'] is False and result['gate_passed'] is False
    assert result['publication_authorized'] is False and result['writes']==0
    assert site(row,receipt,registry)==result and (row,receipt,registry)==before


@pytest.mark.parametrize('change',['not_present','truncated','unverified','bad_type','metadata_mismatch','text_tampered','wrong_source','duplicate_evidence'])
def test_unverified_or_ambiguous_inputs_never_corroborate(change):
    row,receipt,registry=fixture();source=receipt['result']['records'][0]['evidence'][0]
    if change=='not_present':source['text']='A different source text';source['text_sha256']=hashlib.sha256(source['text'].encode()).hexdigest()
    if change=='truncated':row['abstract_truncated']=True
    if change=='unverified':row.pop('abstract_integrity_status')
    if change=='bad_type':source['metadata']['citation_article_type']=['slides']
    if change=='metadata_mismatch':source['metadata']['citation_title']=['Other paper']
    if change=='text_tampered':source['text']+=' changed'
    if change=='wrong_source':source['final_url']='https://unrelated.example/paper'
    if change=='duplicate_evidence':receipt['result']['records'][0]['evidence'].append(deepcopy(source))
    result=audit(row,'weekly',receipt,registry,now=NOW)
    assert result['status']=='held' and result['writes']==0
    assert site(row,receipt,registry)==result

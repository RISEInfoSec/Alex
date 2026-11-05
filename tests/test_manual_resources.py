import copy,json
from pathlib import Path
import pytest
from alex.resource_types import validate_assessment,validate_taxonomy,validate_release,dry_run,digest,corpus_value

ROWS=json.loads((Path(__file__).parent/'fixtures/manual_resources.json').read_text())

@pytest.mark.parametrize('row',ROWS)
def test_real_resource_roundtrip_preserves_actual_type_and_qualitative_assessment(row):
    validate_assessment(row);validate_taxonomy(row)
    output=dry_run(row)
    assert output['document_type']==row['document_type']
    assert output['summary_kind']=='editorial_synopsis'
    assert output['seminal'] is None
    assert output['quality_tier']=='Qualitative assessment'
    assert digest(output)==row['target_schema']['evidence']['target_record_sha256']

@pytest.mark.parametrize('defect',['type','content','assessment','criterion','date','source','numeric','automatic','summary','taxonomy'])
def test_fail_closed_on_changed_or_incomplete_resource(defect):
    r=copy.deepcopy(ROWS[0])
    if defect=='type':r['document_type']='presentation_slides'
    if defect=='content':r['abstract']+=' changed'
    if defect=='assessment':r['resource_assessment']['limitations']='changed'
    if defect=='criterion':r['resource_assessment']['criteria'].pop('actionable_scope')
    if defect=='date':r['publication_date']='2026-10-01'
    if defect=='source':r['resource_assessment']['text_sha256']=''
    if defect=='numeric':r['resource_assessment']['quality_score']=80
    if defect=='automatic':r['automatic_route_eligible']=True
    if defect=='summary':r['summary_kind']='source_abstract'
    if defect=='taxonomy':r['taxonomy']['evidence']['resource_assessment_sha256']='0'*64
    with pytest.raises(ValueError):validate_taxonomy(r)

def approved(row):
    r=copy.deepcopy(row)
    r['authorization']={'route':'human_approved','decision':'approved','content_sha256':r['content_sha256'],
        'resource_assessment_sha256':r['resource_assessment_sha256'],
        'submission':{'id':'TEST-ONLY-human-submission','revision':1,'payload_hash':'1'*64}}
    r['source_revalidation']={'url':r['source_url'],'kind':'exact_pdf' if r['document_type']=='best_practice_guide' else 'exact_resource_html','expected_sha256':r['resource_assessment']['source_sha256']}
    return r

@pytest.mark.parametrize('row',ROWS)
def test_policy_approval_cannot_publish_but_current_manual_decision_can_validate(row):
    with pytest.raises(ValueError,match='human approval'):validate_release(row)
    validate_release(approved(row))

@pytest.mark.parametrize('defect',['auto','stale_content','stale_assessment','no_submission','zero_revision','source','target','quality_binding'])
def test_release_rejects_missing_or_stale_manual_evidence(defect):
    r=approved(ROWS[0])
    if defect=='auto':r['authorization']['route']='existing_regular_automatic_acceptance'
    if defect=='stale_content':r['authorization']['content_sha256']='0'*64
    if defect=='stale_assessment':r['authorization']['resource_assessment_sha256']='0'*64
    if defect=='no_submission':r['authorization']['submission']={}
    if defect=='zero_revision':r['authorization']['submission']['revision']=0
    if defect=='source':r['source_revalidation']['expected_sha256']='0'*64
    if defect=='target':r['target']['document_type']='research_paper'
    if defect=='quality_binding':r['preflight']['checks']['quality']['evidence']['resource_assessment_sha256']='0'*64
    with pytest.raises(ValueError):validate_release(r)

def test_technical_report_requires_methods_and_data_provenance():
    r=copy.deepcopy(ROWS[0]);r['document_type']=r['verified_document_type']='technical_report'
    r['resource_assessment']['actual_type']='technical_report'
    from alex.resource_types import HASH_FIELDS
    r['content_sha256']=digest({k:r.get(k,'') for k in HASH_FIELDS});r['resource_assessment']['content_sha256']=r['content_sha256']
    r['resource_assessment_sha256']=digest(r['resource_assessment'])
    with pytest.raises(ValueError,match='methods'):validate_assessment(r)
    for key in ('methods','data_provenance'):r['resource_assessment']['criteria'][key]={'status':'passed','evidence':'Synthetic test evidence; never a production assessment.'}
    r['resource_assessment_sha256']=digest(r['resource_assessment']);validate_assessment(r)

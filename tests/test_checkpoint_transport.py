import hashlib,json
import pytest
from tools.content_review.checkpoint_transport import metadata,chunk,validate

def test_large_multibyte_checkpoint_roundtrip(tmp_path):
    p=tmp_path/'manifest.json';p.write_text(json.dumps({'records':[{'candidate_id':'candidate','text':'é😀'*400000}]},ensure_ascii=False))
    m=metadata(p);content=''.join(chunk(p,i)['content'] for i in range(m['chunks']))
    assert content==p.read_text() and len(content.encode())==m['size']
    assert hashlib.sha1(b'blob '+str(m['size']).encode()+b'\0'+content.encode()).hexdigest()==m['git_blob_sha']

@pytest.mark.parametrize('text',['{\n... 3578800 bytes omitted ...\n}', '[truncated]', '... 100 chars truncated ...', '{"records": ['])
def test_truncation_or_malformed_json_stops_checkpoint(text):
    with pytest.raises(ValueError):validate(text,'manifest.json')

def test_metadata_change_for_other_type_does_not_reopen_paper_failures():
    from tools.content_review.lifecycle import evidence_key,DEFAULT_POLICY
    row={'content_sha256':'same','document_type':'research_paper'}
    policy={**DEFAULT_POLICY,'type_capability_revisions':{'best_practice_guide':'manual-text-resources-v1'}}
    assert evidence_key(row,policy)==evidence_key(row,DEFAULT_POLICY)

def test_source_activity_cannot_hide_stalled_downstream_gates():
    from tools.content_review.work_plan import processing_progress
    receipts=[{'run_id':str(i),'trigger':'schedule','started_at':str(i),'pilot':{
        'attempted_candidate_ids':[str(i)],'requests':{'source':5},'resolvable_gate_count':2,
        'newly_passed_checks':{'access':[str(i)],'format':[str(i)]},'manual_admitted':[],
        'all_candidates_legitimately_held':False}} for i in range(2)]
    result=processing_progress(receipts)
    assert result['status']=='stalled_downstream_gates' and result['corrective_action']

def test_corrected_checkpoint_failure_cannot_promote_pilot_or_claim_recovery():
    from tools.content_review.pilot_budget import candidate_limit
    from tools.content_review.work_plan import processing_progress
    policy={'id':'pilot','initial_candidate_limit':5,'subsequent_candidate_limit':10,'initial_successful_passes':2}
    receipts=[{'run_id':str(i),'trigger':'schedule','started_at':str(i),
        'native_terminal_verified':True,'status':'complete','pilot':{
        'pilot_id':'pilot','integrity_passed':True,'budget_compliant':True,
        'access_rules_preserved':True,'lease_conflicts':0,'checkpoint_failures':0,
        'attempted_candidate_ids':['candidate'],'requests':{'source':5},
        'newly_passed_checks':{'access':['candidate']}}} for i in range(2)]
    repairs=[{'affected_run_id':'1','prior_integrity_claim_corrected':True}]
    assert candidate_limit(policy,receipts)==10
    assert candidate_limit(policy,receipts,repairs)==5
    progress=processing_progress(receipts,repairs)
    assert progress['status']=='checkpoint_integrity_failed'
    assert progress['runs'][-1]['source_gate_passes']==1
    assert progress['runs'][-1]['checkpoint_integrity']=='failed_corrected'
    receipts[-1]['pilot']['promotion_eligible']=False
    assert candidate_limit(policy,receipts)==5
    # A later intact pass ends the current checkpoint incident, while preserving
    # the correction in historical evidence.
    later={**receipts[0],'run_id':'2','started_at':'2'}
    assert processing_progress(receipts+[later],repairs)['status']!='checkpoint_integrity_failed'

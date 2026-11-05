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

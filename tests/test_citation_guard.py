import json
import pytest
from scripts import citation_guard

@pytest.fixture
def root(tmp_path,monkeypatch):
    (tmp_path/'data').mkdir()
    source=tmp_path/'data/discovery_candidates.csv'
    source.write_text('title\nSynthetic\n')
    # Synthetic, already-reconciled prior output; never create this in live state without reconciliation.
    citation_guard._write(tmp_path/'data/citation_run_guard.json',{'schema_version':1,'status':'complete',
        'run_id':'100','run_attempt':'1','input_sha256':citation_guard._sha(source),
        'output_sha256':citation_guard._sha(source)})
    monkeypatch.setenv('GITHUB_RUN_ID','12345')
    monkeypatch.setenv('GITHUB_RUN_ATTEMPT','1')
    return tmp_path


def evidence(root):
    marker=json.loads((root/'data/citation_run_guard.json').read_text())
    source=root/'data/discovery_candidates.csv'
    rows=[{'event':'begin','schema_version':1,'replay_allowed':False,'context':{'input_sha256':marker['input_sha256']}},
          {'event':'prepared','output_sha256':citation_guard._sha(source)}]
    (root/'data/citation_response_evidence-synthetic.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in rows))


def test_interrupted_attempt_cannot_automatically_restart(root):
    citation_guard.begin(root)
    guard=root/'data/citation_run_guard.json';before=guard.read_bytes()
    with pytest.raises(RuntimeError,match='incomplete or unverified'):
        citation_guard.begin(root)
    assert guard.read_bytes()==before


def test_completed_attempt_binds_output_and_next_attempt(root,monkeypatch):
    citation_guard.begin(root);citation_guard.acknowledge(root)
    (root/'data/discovery_candidates.csv').write_text('title\nCompleted\n')
    evidence(root);citation_guard.complete(root)
    marker=json.loads((root/'data/citation_run_guard.json').read_text())
    assert marker['status']=='complete'
    monkeypatch.setenv('GITHUB_RUN_ID','12346')
    citation_guard.begin(root)
    marker=json.loads((root/'data/citation_run_guard.json').read_text())
    assert marker['status']=='started' and marker['run_id']=='12346'


def test_start_requires_acknowledgement_bound_to_guard_and_input(root):
    source=root/'data/discovery_candidates.csv'
    citation_guard.begin(root)
    input_sha=citation_guard._sha(source)
    with pytest.raises(RuntimeError):
        citation_guard.verify_start(root,input_sha)
    citation_guard.acknowledge(root)
    citation_guard.verify_start(root,input_sha)
    with pytest.raises(RuntimeError,match='not acknowledged'):
        citation_guard.verify_start(root,'0'*64)
    guard=root/'data/citation_run_guard.json'
    record=citation_guard._read(guard);record['run_id']='999'
    citation_guard._write(guard,record)
    with pytest.raises(RuntimeError,match='not acknowledged'):
        citation_guard.verify_start(root,input_sha)


def test_quality_output_is_bound_before_next_discovery(root,monkeypatch):
    citation_guard.begin(root);citation_guard.acknowledge(root);evidence(root);citation_guard.complete(root)
    citation_guard.quality_begin(root)
    source=root/'data/discovery_candidates.csv';source.write_text('title\nQuality output\n')
    citation_guard.quality_complete(root)
    marker=json.loads((root/'data/citation_run_guard.json').read_text())
    assert marker['quality_output_sha256']==citation_guard._sha(source)
    assert marker['quality_input_sha256']==marker['output_sha256']
    monkeypatch.setenv('GITHUB_RUN_ID','12346')
    prior=citation_guard._sha(source)
    source.write_text('title\nNext discovery\n')
    receipt={'status':'complete','orchestration_pass_id':'12346:1:1','deferred_tasks':{}}
    receipt_path=root/'data/discovery_run_receipt.json';receipt_path.write_text(json.dumps(receipt))
    recovery={'schema_version':1,'status':'complete','run_id':'12346:1',
              'starting_candidates_sha256':prior,'final_candidates_sha256':citation_guard._sha(source),
              'passes':[{'status':'complete','returncode':0,'pass_id':'12346:1:1',
                         'receipt':receipt,'receipt_sha256':citation_guard._sha(receipt_path)}]}
    (root/'data/discovery_recovery_receipt.json').write_text(json.dumps(recovery))
    citation_guard.begin(root)


def test_quality_rejects_unverified_or_changed_input(root):
    citation_guard.begin(root);citation_guard.acknowledge(root);evidence(root);citation_guard.complete(root)
    source=root/'data/discovery_candidates.csv';source.write_text('title\nUnexpected\n')
    with pytest.raises(RuntimeError,match='Quality input'):
        citation_guard.quality_begin(root)


def test_quality_completion_rejects_changed_guard(root):
    citation_guard.begin(root);citation_guard.acknowledge(root);evidence(root);citation_guard.complete(root)
    citation_guard.quality_begin(root)
    guard=root/'data/citation_run_guard.json';record=citation_guard._read(guard)
    record['output_sha256']='0'*64;citation_guard._write(guard,record)
    with pytest.raises(RuntimeError,match='Quality completion'):
        citation_guard.quality_complete(root)


def test_changed_output_or_corrupt_guard_refuses_restart(root,monkeypatch):
    citation_guard.begin(root);citation_guard.acknowledge(root);evidence(root);citation_guard.complete(root)
    (root/'data/discovery_candidates.csv').write_text('title\nChanged\n')
    monkeypatch.setenv('GITHUB_RUN_ID','12346')
    with pytest.raises(RuntimeError,match='incomplete or unverified'): citation_guard.begin(root)
    (root/'data/citation_run_guard.json').write_text('{"status":"complete"}')
    with pytest.raises(RuntimeError,match='invalid'): citation_guard.begin(root)


def test_different_attempt_cannot_complete_previous_attempt(root,monkeypatch):
    citation_guard.begin(root);citation_guard.acknowledge(root);monkeypatch.setenv('GITHUB_RUN_ATTEMPT','2')
    with pytest.raises(RuntimeError,match='does not match'): citation_guard.complete(root)


def test_missing_guard_requires_prior_reconciliation(root):
    (root/'data/citation_run_guard.json').unlink()
    with pytest.raises(RuntimeError,match='guard absent'):
        citation_guard.begin(root)
    assert not (root/'data/citation_run_guard.json').exists()


def test_missing_or_changed_evidence_cannot_complete(root):
    citation_guard.begin(root);citation_guard.acknowledge(root)
    with pytest.raises(RuntimeError,match='evidence missing'): citation_guard.complete(root)
    evidence(root)
    p=root/'data/citation_response_evidence-synthetic.jsonl'
    p.write_text(p.read_text().replace('prepared','incomplete'))
    with pytest.raises(RuntimeError,match='evidence invalid'): citation_guard.complete(root)


def test_guard_accepts_actual_offline_citation_evidence(root,monkeypatch):
    import pandas as pd
    from unittest.mock import Mock,patch
    from alex.pipelines import citation_chain
    source=root/'data/discovery_candidates.csv'
    pd.DataFrame([{'title':'Synthetic seed','citation_count':1}]).to_csv(source,index=False)
    citation_guard._write(root/'data/citation_run_guard.json',{'schema_version':1,'status':'complete',
        'run_id':'100','run_attempt':'1','input_sha256':citation_guard._sha(source),'output_sha256':citation_guard._sha(source)})
    citation_guard.begin(root);citation_guard.acknowledge(root)
    response=Mock(status_code=200);response.json.return_value={'results':[]}
    monkeypatch.setattr('alex.utils.http.time.sleep',lambda _:None)
    with patch('alex.utils.io.ROOT',root),patch('alex.pipelines.citation_chain.connector_config.load',return_value={}),patch.object(citation_chain.BaseHttpClient,'_request_with_retry',return_value=response):
        citation_chain.run()
    citation_guard.complete(root)
    marker=json.loads((root/'data/citation_run_guard.json').read_text())
    assert marker['status']=='complete'
    assert marker['output_sha256']==citation_guard._sha(source)
    assert marker['evidence_sha256']==citation_guard._sha(root/'data'/marker['evidence_name'])


def test_new_discovery_input_requires_matching_completed_current_run(root,monkeypatch):
    import hashlib
    guard_path=root/'data/citation_run_guard.json'
    prior=json.loads(guard_path.read_text())['output_sha256']
    source=root/'data/discovery_candidates.csv';source.write_text('title\nNew discovery\n')
    current=citation_guard._sha(source)
    pass_id='12345:1:1'
    receipt={'status':'complete','orchestration_pass_id':pass_id,'deferred_tasks':{}}
    receipt_path=root/'data/discovery_run_receipt.json'
    receipt_path.write_text(json.dumps(receipt))
    recovery={'schema_version':1,'status':'complete','run_id':'12345:1',
              'starting_candidates_sha256':prior,'final_candidates_sha256':current,
              'passes':[{'status':'complete','returncode':0,'pass_id':pass_id,'receipt':receipt,
                         'receipt_sha256':hashlib.sha256(receipt_path.read_bytes()).hexdigest()}]}
    (root/'data/discovery_recovery_receipt.json').write_text(json.dumps(recovery))
    before=guard_path.read_bytes()
    recovery['run_id']='99999:1'
    (root/'data/discovery_recovery_receipt.json').write_text(json.dumps(recovery))
    with pytest.raises(RuntimeError,match='incomplete or unverified'):citation_guard.begin(root)
    assert guard_path.read_bytes()==before
    recovery['run_id']='12345:1'
    (root/'data/discovery_recovery_receipt.json').write_text(json.dumps(recovery))
    citation_guard.begin(root)
    assert json.loads(guard_path.read_text())['input_sha256']==current


def test_changed_discovery_receipt_cannot_authorize_transition(root):
    import hashlib
    guard=root/'data/citation_run_guard.json';prior=json.loads(guard.read_text())['output_sha256']
    source=root/'data/discovery_candidates.csv';source.write_text('title\nChanged\n')
    receipt={'status':'complete','orchestration_pass_id':'12345:1:1','deferred_tasks':{}}
    path=root/'data/discovery_run_receipt.json';path.write_text(json.dumps(receipt))
    recovery={'schema_version':1,'status':'complete','run_id':'12345:1','starting_candidates_sha256':prior,
              'final_candidates_sha256':citation_guard._sha(source),'passes':[{'status':'complete','returncode':0,
              'pass_id':'12345:1:1','receipt':receipt,'receipt_sha256':hashlib.sha256(path.read_bytes()).hexdigest()}]}
    (root/'data/discovery_recovery_receipt.json').write_text(json.dumps(recovery))
    path.write_text(json.dumps({**receipt,'status':'partial'}))
    with pytest.raises(RuntimeError,match='incomplete or unverified'):citation_guard.begin(root)

from copy import deepcopy
import json
import pytest

import tools.content_review.backlog_identity_precheck as precheck


def inputs():
    candidate={'candidate_id':'c1','title':'Distinct study','doi':'','source_url':'https://example.test/item'}
    return {'main_commit':'a'*40,'manifests':{'m3aawg':{'records':[candidate],'preflight_records':[]}},
            'public':[{'title':'Unrelated study','source_url':'https://else.test/x'}],'original_queue':[],
            'current_queue':[]}


def test_site_identity_screen_is_read_only_and_never_authorizes_a_gate(monkeypatch):
    v=inputs();before=deepcopy(v);monkeypatch.setattr(precheck,'_path_blob',lambda *a:(b'{"records":[]}',{}))
    assert precheck.inspect('.',v,'m3aawg','c1')=='clear' and v==before
    v['public'].append({'title':'Another paper','source_url':'https://example.test/item#different-anchor'})
    assert precheck.inspect('.',v,'m3aawg','c1')=='held'
    v=inputs();v['manifests']['m3aawg']['records'][0]['title']='Non-ASCII é'
    assert precheck.inspect('.',v,'m3aawg','c1')=='clear'
    v['public'].append({'title':'Non-ASCII e'});assert precheck.inspect('.',v,'m3aawg','c1')=='held'


def test_site_identity_screen_fails_closed_when_node_or_inputs_are_unavailable(monkeypatch):
    v=inputs();monkeypatch.setattr(precheck,'_path_blob',lambda *a:(json.dumps({'records':[]}).encode(),{}))
    def broken(*a,**k):raise OSError('private subprocess details')
    monkeypatch.setattr(precheck.subprocess,'run',broken)
    with pytest.raises(ValueError,match='Backlog precheck unavailable'):precheck.inspect('.',v,'m3aawg','c1')

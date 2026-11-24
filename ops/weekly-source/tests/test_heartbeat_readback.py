from datetime import datetime,timezone
import json
import pytest
from tools.content_review.heartbeat_readback import confirm, REVIEW, MAIN, HEARTBEAT

@pytest.mark.parametrize('case',['exact','other_parent','extra_file','different_record','busy','expired','ref_moved','no_commit'])
def test_proof_of_ambiguous_heartbeat(case):
    old, new, review, main, blob = [c*40 for c in 'abcde']
    path='config/content_review_detached_heartbeat.json'
    content=json.dumps({'run_id':'actual','observed_at':'2026-11-24T17:20:23Z','lease_expires_at':'2026-11-24T17:49:00Z'})
    p={'heartbeat_head':old,'review_head':review,'path':path,'content':content,'blob_sha':blob}
    state={REVIEW:review,MAIN:main,HEARTBEAT:old if case=='no_commit' else new}
    commit={'sha':new,'parents':[{'sha':new if case=='other_parent' else old}],'files':[{'filename':path,'sha':blob}]}
    if case=='extra_file':commit['files'].append({'filename':'other','sha':blob})
    def heads(_):
        if case=='ref_moved' and heads.called:return {**state,MAIN:new}
        heads.called=True
        return state
    heads.called=False
    when=datetime.fromisoformat('2026-11-24T17:22:00+00:00' if case=='expired' else '2026-11-24T17:20:28+00:00')
    f=lambda:confirm(None,'hidden',p,main,lambda:when,heads,lambda *a:None,get=lambda q:commit,
      read=lambda *a:((b'other' if case=='different_record' else content.encode()),{'blob_sha':blob}),
      idle=lambda token:case!='busy',wait=lambda s:None)
    if case=='exact':assert f()['commit_sha']==new
    else:
        with pytest.raises(ValueError):f()

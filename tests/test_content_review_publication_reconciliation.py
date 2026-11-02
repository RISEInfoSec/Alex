import copy,hashlib,json
import pytest
from tools.content_review.reconcile_publications import reconcile


def fixtures():
    h='a'*64
    row=dict(candidate_id='weekly-one',content_sha256=h,title='Paper',authors='Author',year=2026,source_url='https://example.org/paper',abstract='Full abstract',decision='pending',automatic_handoff_pending=True)
    target=dict(id=1,title='Paper',author='Author',year=2026,source_url=row['source_url'],summary='Full abstract')
    items=[dict(candidate_id=row['candidate_id'],content_sha256=h,target=target,authorization={'route':'existing_regular_automatic_acceptance'})]
    d=hashlib.sha256(json.dumps(items,sort_keys=True,ensure_ascii=False,allow_nan=False).encode()).hexdigest()
    request=dict(release_id='release',records_sha256=d,records=items)
    receipt=dict(release_id='release',records_sha256=d,checked_at='2026-11-02T20:37:00Z',released=[dict(candidate_id=row['candidate_id'],content_sha256=h)])
    return dict(records=[],preflight_records=[row]),request,receipt,[target]


def invoke(values):
    return reconcile(*values,checked_at='2026-11-02T23:41:00Z',receipt_ref='immutable-receipt',public_url='https://example.org/data/papers.json',public_sha256='b'*64)


def test_completed_release_is_reconciled_once_without_changing_editorial_work():
    values=fixtures();before=copy.deepcopy(values[0]);result,report=invoke(values)
    row=result['preflight_records'][0]
    assert report['automatic_handoff_pending']==0
    assert row['publication_status']=='published_live_verified'
    assert row['decision']==before['preflight_records'][0]['decision']=='pending'
    assert values[0]==before
    assert invoke((result,*values[1:]))[0]==result


@pytest.mark.parametrize('defect',['content','receipt','missing','duplicate','changed_public','rejection','changed_request'])
def test_mismatches_fail_without_rewriting_history(defect):
    m,q,r,p=fixtures()
    if defect=='content':m['preflight_records'][0]['content_sha256']='changed'
    if defect=='receipt':r['records_sha256']='changed'
    if defect=='missing':p.clear()
    if defect=='duplicate':p.append(copy.deepcopy(p[0]))
    if defect=='changed_public':p[0]=dict(p[0],summary='changed')
    if defect=='rejection':m['preflight_records'][0]['decision']='rejected'
    if defect=='changed_request':q['records'][0]['target']['title']='changed'
    original=copy.deepcopy(m)
    with pytest.raises(ValueError):invoke((m,q,r,p))
    assert m==original

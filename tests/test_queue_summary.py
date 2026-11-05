import copy
import pytest
from tools.content_review.queue_summary import summarize


def row(cid):
    return {'candidate_id':cid,'content_sha256':'a'*64,'decision':'pending','review_ready':True,
            'editorial_queue_eligible':True,'review_batch':1,'recommendation_content_sha256':'a'*64,
            'preflight':{'checks':{g:{'status':'passed','content_sha256':'a'*64,'checked_at':'2026-11-05T00:00:00Z','evidence':'Test only'} for g in ('format','access','metadata','duplicates','quality','schema')}}}


def test_all_registered_pools_use_current_gates_and_dispositions_not_old_summary():
    ready=row('ready');held=row('held');held['preflight']['checks']['quality']['status']='unknown'
    approved=row('approved');approved['decision']='approved'
    automatic=row('auto');automatic['automatic_handoff_pending']=True
    stale=row('stale');stale['preflight']['checks']['schema']['content_sha256']='b'*64
    unbound=row('unbound');unbound['recommendation_content_sha256']='b'*64
    m={'weekly':{'ready_count':100,'records':[ready,approved,automatic]},
       'sans':{'preflight_records':[held,stale,unbound]},'corpus-audit':{'records':[row('audit')]},
       'apwg':{'records':[{'review_number':165,'editorial_decision':'approved_quality_hold'}]}}
    before=copy.deepcopy(m);s=summarize(m)
    assert s['ready_total']==1 and s['preflight_pending']==2
    assert s['sources']['weekly']['automatic_publication_pending']==1
    assert s['sources']['sans']['awaiting_recommendation_or_admission']==1
    assert s['sources']['corpus-audit']['ready']==0 and m==before
    m['weekly']['preflight_records']=[ready]
    with pytest.raises(ValueError,match='Duplicate queue identity'):summarize(m)

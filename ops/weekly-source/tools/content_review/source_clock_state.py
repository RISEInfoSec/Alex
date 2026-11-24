"""Read the authoritative review branch state and source worker outcomes."""
import json
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID
from urllib.parse import urlencode

from tools.content_review.github_read_objects import REFS, api, commit, refs
from tools.content_review.verified_inputs import _git, _path_blob

WORKER='config/content_review_worker_status.json'


def inspect(repo, run_id=None):
    if run_id and str(UUID(run_id))!=run_id:
        raise ValueError('Invalid native source run identity')
    heads=refs()
    review=heads[REFS[0]]
    commit(repo,review)
    state=json.loads(_path_blob(repo,review,WORKER)[0])
    current=state.get('current_run') or {}
    history=state.get('run_history',[])
    if not isinstance(history,list) or not isinstance(current,dict):
        raise ValueError('Source worker history invalid')
    rows=[x for x in history+[current] if x.get('run_id')==run_id] if run_id else []
    if len(rows)>1:raise ValueError('Ambiguous source run history')
    requested=rows[0] if rows else {}
    pending=current.get('pending_source_request') or {}
    receipt=None
    if run_id:
        path='config/content_review_run_receipts/'+run_id+'.json'
        if _git(repo,'ls-tree','-z',review,'--',path):
            raw,meta=_path_blob(repo,review,path)
            value=json.loads(raw)
            if value.get('run_id')!=run_id:raise ValueError('Canonical source receipt identity differs')
            receipt={'path':path,'blob':meta['blob_sha'],'reported_status':value.get('status'),'requests':value.get('request_counts')}
    query=urlencode({'branch':'codex/soups-corpus-review','event':'push','per_page':10})
    runs=api('/actions/workflows/content_review_sources.yml/runs?'+query)['workflow_runs']
    def active_status(status):
        query=urlencode({'branch':'codex/soups-corpus-review','event':'push','status':status,'per_page':100})
        data=api('/actions/workflows/content_review_sources.yml/runs?'+query)
        if len(data['workflow_runs'])!=data['total_count']:
            raise ValueError('Active source job inventory incomplete')
        return {r['id'] for r in data['workflow_runs']}
    with ThreadPoolExecutor(max_workers=3) as pool:
        active=sorted(set().union(*pool.map(active_status,
            ('queued','in_progress','waiting','pending','requested'))))
    recovered=bool(run_id and requested.get('application_status')=='failed' and
        requested.get('failure_code')=='reconciliation_hold' and requested.get('application_completed_at') and
        requested.get('request_counts')=={'source':0,'openalex':0,'paid':0} and not requested.get('pending_source_request') and
        not requested.get('accounted_source_requests') and not state.get('lease') and
        any(h.get('owner')=='weekly-source-processing' and h.get('run_id')==run_id and
            ((h.get('status')=='released' and h.get('released_at')==requested.get('application_completed_at')) or
             (h.get('status')=='expired' and h.get('expiry_observed_at')==requested.get('application_completed_at')))
            for h in state.get('lease_history',[])))
    return {'reconciled_zero_request_failure':recovered,'review':review,'main':heads[REFS[1]],'heartbeat':heads[REFS[2]],'lease_owner':(state.get('lease') or {}).get('owner'),
            'lease_run':(state.get('lease') or {}).get('run_id'),'current_run':current.get('run_id'),
            'current_application':current.get('application_status'),'requested_run_observed':bool(rows or receipt),
            'requested_application_status':requested.get('application_status'),'receipt':receipt,
            'pending_request':pending.get('request_id'),'pending_origin':pending.get('origin_run_id'),
            'active_source_job_runs':active,'last_native_source_runs':[
                {k:r.get(k) for k in ('id','status','conclusion','run_attempt','head_sha','html_url')} for r in runs[:3]]}

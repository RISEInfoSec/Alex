"""One explicitly authorized manual retention of already-accounted evidence.

No provider is contacted. Candidate identity is kept in memory and a failed
or ambiguous write is never retried. Scheduled/native success is not claimed.
"""
from tools.content_review.coordinator_heartbeat_transport import read_heads,fetch_heads,REVIEW,MAIN
from tools.content_review.coordinator_lifecycle import start_manual
from tools.content_review.coordinator_source_retention import retain
from tools.content_review.coordinator_source_retention_completion import complete
from tools.content_review.d1_reconcile import select_reconciled
from tools.content_review.site_reconcile_client import read_snapshot
from tools.content_review.source_plan import _unretained_source_results
from tools.content_review.verified_inputs import load_inputs


def select(repo,token,*,heads=read_heads,fetch=fetch_heads,reader=read_snapshot):
    refs=heads(repo);fetch(repo,refs,'manual-retention-preflight')
    inputs=load_inputs(repo,refs[REVIEW],refs[MAIN]);state=inputs['worker_state']
    snapshot,confirmed=reader(token)
    choices=select_reconciled(snapshot,confirmed,inputs['reconciliation_manifests'],inputs['lifecycle'],limit=10000,
        source_progress=state.get('source_last_progress',{}),source_attempts=state.get('source_attempts',{}))
    selected=[]
    for item in choices['selected']:
        if item.get('next_stage')!='source':continue
        manifest=inputs['manifests'].get(item['collection']) or {}
        rows=[row for row in manifest.get('records',[])+manifest.get('preflight_records',[]) if row.get('candidate_id')==item['candidate_id']]
        if len(rows)!=1:raise ValueError('Candidate identity unavailable')
        selected.append({**item,'content_sha256':rows[0].get('content_sha256')})
    pending=_unretained_source_results(repo,refs[REVIEW],state,selected,inputs['manifests'])
    if heads(repo)!=refs:raise ValueError('Source heads changed during retention selection')
    if not pending:return refs,None
    key=sorted(pending)[0];evidence=pending[key]
    if type(evidence.get('native_run_id')) is not int or type(evidence.get('artifact_id')) is not int:
        raise ValueError('Accounted artifact identity unavailable')
    return refs,(*key,evidence['native_run_id'],evidence['artifact_id'])


def run(repo,token,owner,run_id,*,choose=select,begin=start_manual,checkpoint=retain,finish=complete):
    refs,choice=choose(repo,token)
    if choice is None:
        return {'status':'deferred','reason':'no_unretained_evidence','candidate_processing':False,'lease_acquired':False,
                'lease_release_confirmed':None,'reconcile_before_retry':False,'native_completion_verified':False}
    acquired=begin(repo,token,None,owner,run_id,scope='source_retention_only',expected_review_head=refs[REVIEW],expected_main_head=refs[MAIN])
    if not isinstance(acquired,dict) or acquired.get('status')!='lease_started':
        return {'status':'blocked','reason':'manual_retention_lease_unconfirmed','candidate_processing':None,
                'lease_release_confirmed':False,'reconcile_before_retry':True,'native_completion_verified':False}
    review,main=acquired['review_head'],acquired['main_head']
    try:
        current,again=choose(repo,token)
        if current[REVIEW]!=review or current[MAIN]!=main or again!=choice:
            raise ValueError('Retention selection changed after lease')
        collection,candidate,source_run,artifact=choice
        result=checkpoint(repo,token,review,main,owner,run_id,source_run,artifact,collection,candidate)
        if (not isinstance(result,dict) or result.get('status')!='source_retained' or
            result.get('heartbeat_rebound') is not True or result.get('reconcile_before_retry') is not False):
            return {'status':'blocked','reason':'retention_checkpoint_or_heartbeat_unconfirmed','candidate_processing':None,
                    'lease_release_confirmed':False,'reconcile_before_retry':True,'native_completion_verified':False}
        done=finish(repo,token,None,result['commit_sha'],main,owner,run_id,result['receipt_path'])
        if not isinstance(done,dict):raise ValueError('Retention completion response unavailable')
        return {**done,'provider_requests':0,'openalex_requests':0,'paid_requests':0,'publication_verified':False}
    except Exception:
        return {'status':'blocked','reason':'manual_retention_reconcile_lease_and_refs','candidate_processing':None,
                'lease_release_confirmed':False,'reconcile_before_retry':True,'native_completion_verified':False}

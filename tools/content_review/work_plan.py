"""Resume missing work; do not substitute cheap activity for source progress."""
from tools.content_review.lifecycle import current_pass, due

def next_stage(row):
    if row.get('decision','pending') not in ('pending','unreviewed') or row.get('publication_status')=='published_live_verified':return 'complete'
    if not current_pass(row,'duplicates'):return 'duplicates'
    if not all(current_pass(row,g) for g in ('format','access')):return 'source'
    if not current_pass(row,'metadata'):return 'metadata'
    if not current_pass(row,'quality'):return 'quality'
    if not current_pass(row,'schema'):return 'classification_and_serialization'
    return 'recommendation_and_admission'

def select(manifests, ledger, limit=5, source_progress=None):
    candidates=[];source_progress=source_progress or {}
    for collection,manifest in manifests.items():
        for row in manifest.get('records',[])+manifest.get('preflight_records',[]):
            entry=ledger.get('records',{}).get(collection+':'+row['candidate_id'])
            if not entry or not due(entry):continue
            stage=next_stage(row)
            if stage=='complete':continue
            kind=row.get('verified_document_type') or row.get('document_type')
            from alex.resource_types import TYPES
            supported=kind in ('research_paper','research_paper_candidate') or kind in TYPES
            # Supported complete abstracts first; weekly priority within comparable work.
            rank=(not(supported and all(current_pass(row,g) for g in ('format','access','metadata','quality'))),not(supported and len(row.get('abstract',''))>=100),collection!='weekly',
                  source_progress.get(collection,{}).get('at',''),entry.get('first_seen_at',''),row['candidate_id'])
            candidates.append((rank,{'collection':collection,'candidate_id':row['candidate_id'],'next_stage':stage}))
    return [item for _,item in sorted(candidates,key=lambda x:x[0])[:limit]]

def processing_progress(receipts):
    runs=[]
    for receipt in sorted(receipts,key=lambda r:r.get('started_at','')):
        p=receipt.get('pilot',{});counts=p.get('requests',receipt.get('request_counts',{}))
        if not p or receipt.get('trigger')!='schedule':continue
        source_checks=sum(len(v) for k,v in p.get('newly_passed_checks',{}).items() if k in ('format','access','metadata'))
        downstream_checks=sum(len(v) for k,v in p.get('newly_passed_checks',{}).items() if k in ('quality','schema'))
        runs.append({'run_id':receipt.get('run_id'),'local_candidates':len(p.get('attempted_candidate_ids',[])),
                     'candidate_ids':p.get('attempted_candidate_ids',[]),'resolvable_gates':p.get('resolvable_gate_count'),
                     'legitimate_holds_only':p.get('all_candidates_legitimately_held') is True,
                     'source_requests':counts.get('source'),'source_gate_passes':source_checks,'downstream_gate_passes':downstream_checks,
                     'review_ready':len(p.get('manual_admitted',[])), 'six_gate_completions':len(p.get('all_six_completed',[])),
                     'blockers':p.get('remaining_blockers',receipt.get('remaining_blockers',[]))})
    recent=runs[-3:]
    stalled=len(recent)>=2 and all(r['local_candidates'] and r['source_requests']==0 and r['source_gate_passes']==0 and r['review_ready']==0 for r in recent)
    no_progress=len(recent)>=2 and all(r['local_candidates'] and r['source_gate_passes']==0 and r['review_ready']==0 for r in recent)
    resolvable=no_progress and any((r['resolvable_gates'] or 0)>0 for r in recent)
    repeated=no_progress and bool(set(recent[-1]['candidate_ids'])&set(recent[-2]['candidate_ids'])) and not all(r['legitimate_holds_only'] for r in recent)
    downstream_stall=len(recent)>=2 and all(r['local_candidates'] and r['downstream_gate_passes']==0 and r['six_gate_completions']==0 and r['review_ready']==0 for r in recent) and any((r['resolvable_gates'] or 0)>0 for r in recent) and not all(r['legitimate_holds_only'] for r in recent)
    status='stalled_resolvable_gates' if resolvable else 'stalled_local_only' if stalled else 'stalled_downstream_gates' if downstream_stall else 'repeated_attempts_without_progress' if repeated else 'progress_requires_gate_evidence'
    return {'runs':runs,'status':status,
            'corrective_action':'Consume pending source artifacts, then execute next missing gate for due candidates. Verify transport/checkpoint capability; park precise access or type-policy holds and select independent resolvable work. Report the cause and exact remedy.' if stalled or resolvable or repeated or downstream_stall else None,
            'scheduler_success_is_processing_recovery':False}

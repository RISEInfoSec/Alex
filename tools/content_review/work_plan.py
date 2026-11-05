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
    if limit <= 0:return []
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
            rank=(not(supported and all(current_pass(row,g) for g in ('format','access','metadata','quality'))),not(supported and len(row.get('abstract',''))>=100),source_progress.get(collection,{}).get('at',''),collection!='weekly',entry.get('first_seen_at',''),row['candidate_id'])
            candidates.append((rank,{'collection':collection,'candidate_id':row['candidate_id'],'next_stage':stage}))
    # Round-robin within each evidence/readiness tier. Source waiting history
    # precedes weekly preference; weekly wins ties, not every future pass.
    result=[]
    tiers={}
    for rank, item in sorted(candidates,key=lambda x:x[0]):
        tiers.setdefault(rank[:2],{}).setdefault(item['collection'],[]).append((rank,item))
    for tier in sorted(tiers):
        groups=tiers[tier]
        order=sorted(groups,key=lambda c:groups[c][0][0])
        while any(groups.values()):
            for collection in order:
                if groups[collection]:
                    result.append(groups[collection].pop(0)[1])
                    if len(result)>=limit:return result
    return result

def processing_progress(receipts, checkpoint_repairs=()):
    invalid_runs={r.get('affected_run_id') for r in checkpoint_repairs
                  if r.get('prior_integrity_claim_corrected') is True}
    runs=[]
    for receipt in sorted(receipts,key=lambda r:r.get('started_at','')):
        p=receipt.get('pilot',{});counts=p.get('requests',receipt.get('request_counts',{}))
        if not p or receipt.get('trigger')!='schedule':continue
        source_checks=sum(len(v) for k,v in p.get('newly_passed_checks',{}).items() if k in ('format','access','metadata'))
        downstream_checks=sum(len(v) for k,v in p.get('newly_passed_checks',{}).items() if k in ('quality','schema'))
        runs.append({'run_id':receipt.get('run_id'),
                     'checkpoint_integrity':'failed_corrected' if receipt.get('run_id') in invalid_runs else 'failed' if p.get('integrity_passed') is False or (p.get('checkpoint_failures') or 0)>0 else 'reported_passed' if p.get('integrity_passed') is True else 'unknown',
                     'local_candidates':len(p.get('attempted_candidate_ids',[])),
                     'candidate_ids':p.get('attempted_candidate_ids',[]),'resolvable_gates':p.get('resolvable_gate_count'),
                     'legitimate_holds_only':p.get('all_candidates_legitimately_held') is True,
                     'source_requests':counts.get('source'),'source_gate_passes':source_checks,'downstream_gate_passes':downstream_checks,
                     'review_ready':len(p.get('manual_admitted',[])), 'six_gate_completions':len(p.get('all_six_completed',[])),
                     'blockers':p.get('remaining_blockers',receipt.get('remaining_blockers',[]))})
    recent=runs[-3:]
    # A zero-attempt pass is not recovery. Look back across idle/blocked
    # observations until real downstream progress, preserving unknown counters.
    stalled_tail=[]
    for run in reversed(runs):
        if run['downstream_gate_passes'] or run['six_gate_completions'] or run['review_ready']:
            break
        stalled_tail.append(run)
    pending_stall=(len(stalled_tail)>=2
                   and any((r['resolvable_gates'] or 0)>0 for r in stalled_tail)
                   and not all(r['legitimate_holds_only'] for r in stalled_tail))

    stalled=len(recent)>=2 and all(r['local_candidates'] and r['source_requests']==0 and r['source_gate_passes']==0 and r['downstream_gate_passes']==0 and r['six_gate_completions']==0 and r['review_ready']==0 for r in recent)
    no_progress=len(recent)>=2 and all(r['local_candidates'] and r['source_gate_passes']==0 and r['review_ready']==0 for r in recent)
    resolvable=no_progress and any((r['resolvable_gates'] or 0)>0 for r in recent)
    repeated=no_progress and bool(set(recent[-1]['candidate_ids'])&set(recent[-2]['candidate_ids'])) and not all(r['legitimate_holds_only'] for r in recent)
    downstream_stall=len(recent)>=2 and all(r['local_candidates'] and r['downstream_gate_passes']==0 and r['six_gate_completions']==0 and r['review_ready']==0 for r in recent) and any((r['resolvable_gates'] or 0)>0 for r in recent) and not all(r['legitimate_holds_only'] for r in recent)
    checkpoint_failed=bool(recent and recent[-1]['checkpoint_integrity'] in ('failed','failed_corrected'))
    status='checkpoint_integrity_failed' if checkpoint_failed else 'stalled_resolvable_gates' if resolvable else 'stalled_local_only' if stalled else 'stalled_downstream_gates' if downstream_stall else 'repeated_attempts_without_progress' if repeated else 'stalled_resolvable_gates' if pending_stall else 'progress_requires_gate_evidence'
    return {'runs':runs,'status':status,
            'corrective_action':'Verify the restored checkpoint and use lossless blob-verified transport. Preserve actual source progress, exclude the failed pass from promotion, and require a later intact scheduled checkpoint to establish recovery.' if checkpoint_failed else 'Consume pending source artifacts, then execute next missing gate for due candidates. Verify transport/checkpoint capability; park precise access or type-policy holds and select independent resolvable work. Report the cause and exact remedy.' if pending_stall or stalled or resolvable or repeated or downstream_stall else None,
            'unresolved_stall_run_ids':[r['run_id'] for r in reversed(stalled_tail)] if pending_stall else [],
            'actionable_blockers':[b for r in reversed(stalled_tail) for b in r['blockers']] if pending_stall else [],
            'scheduler_success_is_processing_recovery':False}

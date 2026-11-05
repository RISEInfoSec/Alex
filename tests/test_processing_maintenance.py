import copy
from tools.content_review.work_plan import processing_progress, select

def receipt(run, attempts, resolvable=3, schema=0, held=False):
    return {"run_id":run, "trigger":"schedule", "status":"complete", "started_at":run,
            "pilot":{"attempted_candidate_ids":attempts, "requests":{"source":0},
                     "newly_passed_checks":{"schema":["x"] if schema else []},
                     "manual_admitted":[], "all_six_completed":[],
                     "resolvable_gate_count":resolvable,
                     "all_candidates_legitimately_held":held, "integrity_passed":True,
                     "remaining_blockers":[{"stage":"classification_and_serialization",
                                            "corrective_action":"Install declared dependencies in authorized runtime"}]}}

def test_zero_attempt_pass_does_not_clear_known_resolvable_stall():
    result=processing_progress([receipt("1",["x"]),receipt("2",[]),receipt("3",[],None)])
    assert result["status"]=="stalled_resolvable_gates"
    assert result["corrective_action"]
    assert result["actionable_blockers"][0]["stage"]=="classification_and_serialization"

def test_real_downstream_progress_ends_prior_stall_window():
    result=processing_progress([receipt("1",["x"]),receipt("2",[]),receipt("3",["x"],schema=1)])
    assert result["status"]=="progress_requires_gate_evidence"
    assert not result["unresolved_stall_run_ids"]

def test_legitimate_holds_do_not_create_resolvable_stall():
    result=processing_progress([receipt("1",[],0,held=True),receipt("2",[],0,held=True)])
    assert not result["unresolved_stall_run_ids"]

def test_corrected_integrity_is_not_overridden_by_stall_detection():
    result=processing_progress([receipt("1",["x"]),receipt("2",[])],
                               [{"affected_run_id":"2","prior_integrity_claim_corrected":True}])
    assert result["status"]=="checkpoint_integrity_failed"

def test_comparable_sources_rotate_without_weekly_monopoly(monkeypatch):
    import tools.content_review.work_plan as plan
    monkeypatch.setattr(plan,"current_pass",lambda row, gate:gate!="schema")
    collections=["weekly","soups","first","m3aawg","bellingcat","sans","virusbulletin"]
    manifests={c:{"records":[{"candidate_id":c+str(i),"document_type":"research_paper",
                             "abstract":"a"*150} for i in range(10)]} for c in collections}
    ledger={"records":{c+":"+r["candidate_id"]:{"state":"awaiting_initial_checks",
                      "first_seen_at":"2026-01-01"} for c,m in manifests.items() for r in m["records"]}}
    progress={}
    seen=set()
    for turn in range(3):
        chosen=select(manifests,ledger,limit=5,source_progress=progress)
        assert len({r["collection"] for r in chosen})==5
        if turn==0:assert chosen[0]["collection"]=="weekly"
        for r in chosen:
            seen.add(r["collection"])
            progress[r["collection"]]={"at":"2026-11-0"+str(turn+1)}
    assert seen==set(collections)
    assert select(manifests,ledger,limit=0)==[]

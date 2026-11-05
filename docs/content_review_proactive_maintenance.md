# Standing maintenance responsibility — 5 November 2026

The owner authorizes routine reversible repairs to the ALEX tools and processes across every collection, weekly discovery and existing-corpus maintenance. The review branch name does not limit scope. The existing Content Review worker owns diagnosis, repair and verification; the independent monitor observes and escalates but does not become a second writer or processor.

On every pass, read config/content_review_defects.json before candidate selection. A repeated actionable failure or two passes without downstream progress must produce one of: a concrete repair with regression evidence; a bounded diagnostic action with its result; or an escalation naming the actual restriction, proposed fix, benefit, risks and exact decision needed. Merely copying the previous blocker is not completion. Do not spend new provider requests to demonstrate a known software failure.

A runtime with missing declared dependencies is a capability defect: install the declared dependencies using the authorized setup, verify imports, and resume retained work. An actual access or approval denial remains binding; record it and request the specific intervention. Monitor-only instructions apply to the independent observer, not the owner-authorized processing or maintenance role. Never replay a denied action through a different route.

## Required defect record and completion evidence

Each defect has a stable ID, affected collections/routes, immutable evidence, observed cause, next action, owner role, status and verification criteria. Keep implemented, CI-tested, maintenance-demonstrated, scheduled-verified and live-published separate. Preserve historical failures and receipts; corrections are append-only evidence. A zero-attempt pass cannot clear a known resolvable stall. work_plan.processing_progress supplies unresolved_stall_run_ids and actionable_blockers to both worker health and independent monitoring.

Before each pass ends, update the defect's evidence and next action under the shared lease. If the pass budget cannot accommodate a repair, checkpoint a reproducible diagnosis or prepared patch and explicitly escalate the runtime/authority constraint; do not claim it was repaired. The monitor records the affected defect and actual corrective action in its own snapshot only. It never changes worker state or schedules.

## Coverage and distinct routes

| Collection / route | Implementation and legitimate deferrals |
| --- | --- |
| Weekly discovery | Additive upstream identities, normalized paper preflight and paid handoff; qualifying automatic acceptance remains separate from manual review. |
| SOUPS | Normalized paper hash contract; curated manual batches remain mandatory. |
| SANS | Shared normalized paper contract; actual guides/reports use the manual text-resource route where eligible. |
| FIRST | Shared normalized contract; preserve withheld asset and TLP restrictions; public guides assessed independently. |
| M3AAWG | Shared paper contract plus manual guide/report route; preserve editions, translations and attribution. |
| Bellingcat | Shared paper contract plus manual investigative-journalism route; no paper bibliometric substitution. |
| Virus Bulletin | Existing normalized legacy inventory and controlled collection executor; paid_worker.MANIFESTS does not currently support its hash contract. Diagnose and test that adapter separately before enabling paid work. Preserve curated decisions and media holds. |
| APWG eCrime | Distinct apwg_pending adapter and controlled APWG import; annual 2026 full-paper check remains scheduled for December. Do not pretend the shared paper handoff covers it. |
| Consensus | Disabled pending secure credential, verified Free account, durable budget and operator enablement; do not use paid access or another credential path. |
| Corpus relevance audit | Distinct corpus_audit adapter; reconcile completed keeps/removals and exclusions. Never reimport removed content or count completed audit work as intake throughput. |

Use current registry/configuration, not this table's prose, for active counts. Enumerate every collection in each pass receipt with selected IDs or an evidence-backed deferral. For comparable due candidates, work_plan.select rotates collection groups using last actual progress; weekly wins a tie but cannot monopolize successive passes. Persist source_last_progress only for actual useful progress; polling/heartbeat does not reset waiting age. Discovery not yet due does not defer ingested preflight.

## Known failure chain

Immutable source receipt 6e85535d... already contained the missing journal venue. It was not transferred into the candidate's canonical venue, while metadata was labelled passed. Dependency errors then stopped handoff preparation. The 14:45 UTC worker receipt records an installation denial under stale monitor-only scope; a later authorized maintenance pass repaired dependencies. This is evidence of both a role/scope conflict and an implementation gap, not missing owner publication authority.

Publication run 41945055902 passed individual release tests, then failed in resource_types.validate_assessment during mixed-corpus publish. The tests omitted mixed CSV inference. PR112 preserves exact raw resource values and checks the original binding, rather than weakening assessment or approval requirements.

The progress detector required nonzero candidate attempts in every recent pass, so dependency-blocked zero-attempt passes could erase its stall warning. The source selector ranked weekly ahead of last source progress, allowing comparable named sources to wait indefinitely. These shared defects require code/tests and subsequent scheduled evidence, not another success label.

Full recovery requires later existing scheduled runs with independent native terminal proof, canonical intact receipts, compliant heartbeats/budgets, useful work across eligible routes, and actual downstream completions. A CI pass, a redirected/no-work pass or one ready record is insufficient. No new schedule is authorized or needed.

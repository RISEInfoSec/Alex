# Operations and candidate lifecycle — 2 November 2026

The owner approved this policy and implementation. Preserve every editorial decision,
candidate identity, content version and prior source/paid result. No score threshold changes.

## Single existing hourly worker

Use Automation_4eb2dd829aa88191b542d57f7008ebe3 linked to Site
appgprj_6ae0e13117b48191b3b024311ee18342. Do not create a replacement schedule.
Read native automations.peek and sites.get_site on every run; recorded enabled flags in
repository prose are not authoritative. Persist only sanitized scheduler fields in
config/content_review_operations.json: observation timestamp, enabled, next_run_time,
latest native run ID/state/trigger and last verified scheduled completion. Never copy
prompts, user IDs, tokens, arbitrary logs or account details into health snapshots.

The worker was disabled at the November 2 audit. The native record has a failed attempt,
requires_user_action=true and no diagnostic text. The available evidence does not identify
who/what paused it or explain the failure. Earlier repository enabled assertions were stale.
Never infer recovery from toggling enabled, a manual chat, run_now, or a repository timestamp.

## At each scheduled pass

1. Read this document, current background-worker/workflow instructions, native scheduler
   state, current lifecycle ledger/policy, D1 completed decisions and current main exclusions.
2. Acquire and read back the shared SHA-guarded lease. Expired/stale/foreign leases do not
   authorize competing writes. A failed lease acquisition does not count as a candidate attempt.
3. Before changing candidates, compare the previous native run with the immutable heartbeat
   receipt under config/content_review_run_receipts/. A verified scheduled completion requires
   the matching native terminal success/no_update record, actual receipt/checkpoint and a
   scheduled trigger (or a scheduled_for matching the saved schedule). Never mark the current
   still-running pass successful in advance. A manual run cannot satisfy this proof.
4. Publish already eligible approvals first through existing supported paths.
5. Run python -m tools.content_review.lifecycle --run-id LEASE_RUN_ID --write. Use
   lifecycle.due(entry) to select candidate work. Inactive entries must not consume requests.
6. Complete bounded real missing checks on due candidates. Record one actual candidate
   resolution attempt per candidate/action/run with record_attempt(), a unique attempt_id,
   checked stage, outcome, precise reason and an immutable evidence/checkpoint reference.
   Checkpoint each result immediately and re-evaluate that candidate. Do not increment attempts
   for scheduler wakes, skipped work, reuse of cached evidence, source cooldowns, or migration.
   The identity must be idempotent across replay. Success records last_progress_at.
7. Run bounded due source discovery and preserve all original archive/weekly identities.
   Discovery suppression consults the lifecycle ledger even if a candidate leaves a manifest.
   Changed source observations stay separate until verified. To reconsider an inactive entry,
   reconcile the real change into current content or lifecycle_evidence_revision; record the
   evidence reference. Capability/permission revisions change only after a verified relevant fix.
8. Save/read back lifecycle counts, source checkpoints, native scheduler observation and
   provider incidents. Preserve a dated run receipt with actual start/end, native run ID when
   supplied, scheduled_for/trigger when independently available, completed actions, candidate
   IDs, actual request counts, checkpoint paths and errors. Missing run identity stays unknown.
   Do not claim a fresh heartbeat means a successful completed run.
9. Release the lease in finally. Failure must preserve the last successful completion and
   record the specific failed stage. Never pause the scheduler for ordinary candidate holds,
   empty queues, provider cooldowns or a normal no-change pass.

## Lifecycle policy

Initial checks: warn after 48 hours; scheduler neglect never retires an untouched candidate.
Temporary failures: initial attempt plus retries on days 1,3,7,14 after the first failure;
maximum five actual attempts or 30 days from first failure, whichever first. Longer
provider cooldowns always win. Run ledger evaluation even while waiting so age limits apply.
Stable verified hard-gate failures stop unchanged retries. Unsupported verified resource
types wait for a compatible capability; access/TLP restrictions wait for verified permission.
Exhausted evidence/identity conflicts retire unresolved with the actual reason. An actionable,
worthwhile editorial choice may be parked as operator_action_required with a concrete question;
never delegate routine mechanical checks to the operator. Access failure is not scientific rejection.
Retired/parked entries remain searchable with immutable evidence and complete history.
No retirement reverses human approval/rejection or removes an existing public record.
Do not fabricate historical attempt counts. All attempts before migration remain in the
existing source/checkpoint evidence; the new ledger explicitly labels incomplete old counts.

## Health reporting contract

The console reads config/content_review_operations.json and the lifecycle ledger without
redeployment. Native scheduler observations expire after 90 minutes. A missed next execution
plus 15 minutes is Overdue; an old success cannot make an enabled worker Operating normally.
Live GitHub workflow state/run evidence is refreshed independently by the console. Paused,
Failed, Running, Idle, Degraded, Overdue and Status unknown are distinct conditions.
OpenAlex and other incidents retain onset, impact, latest verified result, retry_not_before,
recovery evidence and operator action. An elapsed cooldown alone is not recovery. Old
successes are historical observations, not a fresh API availability probe. Do not spend a
paid or rate-limited call only to make a dashboard green.

When native next_run_time is unavailable, operations.expected_next() preserves the expected due time from the saved hourly schedule and the latest matching native scheduled_for. Label it as expected, not native. Never roll an unexecuted due time forward merely because the page refreshed; a missed run must become Overdue.

## Scheduler-record replacement and complete manifest writes

The original task Automation_0ff7fb9b800481919b48ddb2593b8f88 is RETIRED and disabled after native failures for the 17:00 and 17:15 Toronto scheduled attempts, despite persisted application work and normal final reports. Do not re-enable it. Its receipts/history remain unchanged. The sole active task is Automation_4eb2dd829aa88191b542d57f7008ebe3, registered through the Site and awaiting scheduled verification. Read the current ID from workflow configuration rather than historical receipts.

Use operations.observe() or its CLI to build the scheduler observation and expected due time; do not hand-build a rolling next-run timestamp. Save canonical receipts at config/content_review_run_receipts/<actual_native_run_id>.json with run_id, trigger, scheduled_for, completed_at, status, completed_actions and receipt_path. An application receipt never overrides native failure.

The second recovery pass repaired invalid weekly JSON introduced by a literal connector truncation marker. Before any manifest update, obtain complete immutable bytes or a verified checkout, validate them with tools/content_review/manifest_integrity.py, and preserve every prior candidate identity, reviewed hash and human decision. Do not write model-context excerpts or reconstructed partial manifests. Use validate_update() before and after write; explicitly reconcile authorized content/decision changes. The discovery writer now enforces this guard. A push-triggered integrity workflow independently validates complete source manifests and reports any violation. Never bypass a failing integrity check or reclassify it as success.


## Immediate start, heartbeat and operator Refresh

### Runtime readiness and heartbeat work windows — repair 5 November 2026

After publishing/readback of start status, run `python -m tools.content_review.runtime_guard --check-dependencies` using the same interpreter as the handoff. It tests actual imports of paid/source preparation and their declared dependencies without a provider call. A missing local package is a runtime setup failure, not a failed paper or unavailable repository credential. Install declared requirements through the supported package route with `python -m pip install -r requirements.txt` when authorized, then rerun the check. Do not silently repeat an unchanged missing-package hold each hour. If installation is denied, record the exact denial and runtime limitation; never bypass it. Setup time remains inside the original native-start budget.

Use asynchronous execution with short polls for installation/tests/runner waits so the lease-owning coordinator can refresh native state and publish/read back both status files. Before each source/paid preparation, checkpoint-transfer group, D1 page group or runner poll, run `python -m tools.content_review.runtime_guard --run-id <actual-native-run-id> --before-work-seconds 20` (or the smaller actual bound). It refuses work if it would consume the completion reserve, outlive the lease, or finish more than40seconds after the last actual heartbeat. On the heartbeat refusal, publish a fresh native-backed running checkpoint immediately and recheck. Keep transfers/polls in bounded groups; do not queue a long sequence of individually short operations without checking between groups. The20-second margin is for native lookup, publication and readback. An unavailable/stalled tool can still cause a gap: report actual timestamps and disqualify that pass rather than backfilling. This guard does not generate heartbeats, prove native completion, or independently establish scheduler recovery.

The independent observer retains ownership of its snapshot. Worker and observer are separate task roles; monitor-only restrictions do not describe a worker maintenance request. The quoted14:45UTC run on5November completed natively, but its dependency blocker and actual heartbeat gaps remain historical facts. Maintenance repair cannot retroactively qualify it for pilot promotion; later scheduled evidence must demonstrate the fix.

Before bundling a paid request, check each selected candidate with `python -m tools.content_review.runtime_guard --candidate weekly/<id> --candidate weekly/<other-id>`. This only builds requests in memory and makes zero provider calls. Resolve or record individual holds, then bundle only the eligible peers within the pilot limit; an incomplete peer must not stall valid ones. Continue to inspect prior exact-hash results and refresh decisions/duplicates before any spend. On5November maintenance validation, two retained papers passed request preparation, while `weekly-56fec07c6bb5ce26240c614e` failed because its required venue is empty. Reconcile that venue from retained verified source evidence before spending; do not invent it or waive the check.

The status panel reads current GitHub contents and workflow runs on every operator Refresh, with no shared response cache and no raw-CDN fallback. Browser auto-refresh is every 30 seconds. Read time, worker activity time and native scheduler observation time are separate. The hosted Site has no direct native Automations read integration; never describe a new GitHub read as a new native scheduler observation.

After native automations.peek and acquiring/readback of the shared lease, BEFORE D1 reconciliation, candidate processing, slow source reads or tests, execute:

```text
python -m tools.content_review.operations --native-observation <actual-native-observation.json> --run-id <actual-native-run-id> --phase start
```

Publish and read back BOTH config/content_review_worker_status.json and config/content_review_operations.json immediately, using the existing SHA guards. The helper records current_run with the actual native started_at, scheduled_for, run ID, observed_at and application state. Do not postpone this first publication until the end of a pass. No candidate attempt is consumed.

During processing, at least once every 60 seconds, fetch the current native observation and repeat with --phase running; publish/read back both files. If execution or publishing is unavailable, preserve the last observation and report the actual blocker. A stopped heartbeat must become visibly degraded; do not keep a stale Running claim. Refresh may display a newly acquired, unexpired scheduled-run lease before its start heartbeat arrives, explicitly labelling that timestamp as lease acquisition rather than native start. Maintenance leases never establish scheduled worker activity.

After writing the actual canonical receipt, execute with --phase complete (or --phase failed for a real application failure), publish/read back both files, and release the lease in finally. Application completion remains separate from native terminal completion; only independently fetched terminal evidence with the exact receipt proves scheduled success. Do not replay processing to update a status label. Preserve current_run when releasing the lease so the console can show the latest completed application state while waiting for independent native confirmation.


## Publication-status reconciliation — corrected 2 November 2026

A native successful worker run is not evidence of review-queue progress or publication-state consistency. The seven-paper incident was a split-state defect: the immutable automatic release succeeded on main, but its review-branch candidates retained pending flags. The console also mislabeled automatic publication as manual batch admission.

Before preparing or retrying any release on EVERY pass, enumerate current main data/content_review_release_receipts and corresponding immutable config/content_review_releases requests. Reconcile successful released candidates against the current deployed public target with tools/content_review/reconcile_publications.py: exact current reviewed hash, receipt/request digest and every public target field must agree. Never use title-only presence, a merged PR, or scheduler completion as publication proof. Missing, changed, duplicate, removed or rejected records must not be inferred published. Preserve historical decisions and explicit removal/exclusion receipts. Do not re-publish to repair a missing completion flag.

Apply the pure reconcile() result only under the verified shared lease, validate complete manifest identities/hashes/decisions before and after, synchronize lifecycle and aggregate counts, and save/read back a dated reconciliation receipt. A repeated reconciliation is idempotent and makes no provider or paid requests. A published or explicitly removed candidate must never re-enter automatic handoffs or manual admission. If publication cannot be independently checked, retain evidence and show that the observation is unavailable; do not call pending counts current.

The public Pages artifact now includes data/review-publications.json generated from its exact accepted corpus and papers.json. The console reads this deployed index without caching on Refresh and matches candidate ID plus reviewed content hash, independently of review-branch flags. Automatic publication pending is distinct from cleared manual admission. This index reports deployed content, not native scheduler state. Saved worker aggregates never override the current collection's evidence.


## Bounded initial-check pilot — authorized 4 November 2026

This section supersedes the first-verification one-candidate/ten-minute restriction. Scheduled execution has already been verified; do not repeat that verification phase. Preserve the existing hourly schedule, task identity and retired-task state. The authoritative budgets are content_review_workflow.json bounded_processing_pilot.

Use tools/content_review/pilot_budget.py Budget for elapsed-time and candidate/request ceilings. Begin its clock at native started_at (including startup/reconciliation), not at the first candidate. A late start with no remaining budget is a deferred pass, not permission to reset the clock. Perform first-five/six-gate work with the current existing executors and verified source evidence, not keyword-only recommendations.

1. Read current native state; acquire/read back the shared SHA-guarded lease and immediately publish the required start status. Finish eligible approvals first, reusing exact-hash evidence. Read completed decisions and current corpus/exclusions once per pass and retain immutable snapshot digests. Recheck changed/time-sensitive inputs before admission/release.
2. Audit up to 200 local candidates without source/model requests. Recompute lifecycle including overdue flags using the existing evaluator; preserve historical unknown attempts. Distinguish untouched, partially checked and specific holds in the receipt. Do not modify completeness labels or provisional types without supporting evidence and the existing explicit version/rebinding procedure.
3. Process up to FIVE distinct due candidates per pass for the first TWO qualifying scheduled passes. Thereafter allow up to TEN only after independently verified receipts satisfy the promotion rule. Retain five if promotion evidence is unavailable. These are ceilings, not a requirement to spend on ineligible records. Multiple related missing subchecks may be completed within one candidate attempt. Do not stop after one cheap duplicate check while useful work remains in budget.
4. Limit source HTTP send attempts to 30, new paid classifications to five and all pass work to 720 seconds, reserving the final 120 seconds for durable checkpoints/receipt/lease release. Every outbound request must fit its bounded timeout in remaining work time. Count robots/redirect sends where observable; record unavailable counts honestly. Paid/OpenAlex work also consumes the shared wall clock and keeps existing stricter transport/request rules.
5. Read independent origins concurrently only where the runtime supports it: maximum three origin lanes, one in-flight request per origin, at least two seconds between requests and a 20-second request timeout; stricter origin rules win. Serial execution remains valid. Only the lease-owning coordinator writes manifests, ledger and checkpoints; never delegate the lease or start competing writers. Persist each candidate result and flush/read back at least every 60 seconds. Stop new work on persistence failure. Keep the existing running heartbeat every 60 seconds.
6. Prefer supported written papers with complete abstracts and resolvable missing gates. Retain existing weekly preparation priority; rotate otherwise comparable eligible sources using waiting age and last-progress checkpoints. Ensure FIRST and M3AAWG are considered alongside the other named sources. A discovery refresh not yet due does not defer already-ingested candidate preflight. Preserve retrospective scope and archive resume positions; enumeration cannot consume the preparation budget. Never repeat stable failures, parked resources, completed HVE source checks or paid work solely for status.
7. Preserve all six gates, scoring thresholds, decisions, exclusions, original identities, actual resource types and evidence. Resolve real independent holds first. Retain one credentialed OpenAlex lookup per pass, 60-second pacing and all provider cooldowns. Review authorization to resume does not erase main's later hold: until effective-policy drift is reconciled through the supported path, honor the longest applicable deadline and record deferral; never switch endpoints/runners to bypass it. Do not launch another weekly retry.
8. Seal any 1–20 fully gate-cleared candidates immediately after substantive current-usefulness recommendations. Keep automatic-route survivors outside manual-ready totals. No relabelling held records as ready, no full-batch minimum, no new non-paper export support implied by this pilot.
9. Append a pilot object to the canonical run receipt: pilot_id; policy/version digest; candidate_limit; selected/attempted/completed candidate IDs; genuinely_first_checked; newly_passed_checks by gate; all_six_completed; manual_admitted; automatic_survivors; explicit_hold_dispositions; cache_reuse; actual source/paid/OpenAlex requests and paid tokens; stage elapsed times; integrity_passed; budget_compliant; access_rules_preserved; lease_conflicts; checkpoint_failures; remaining blockers and source last-progress. Report unknowns as unknown. Include candidate/checkpoint digests and before/after counts. Application completion never proves native success. Promotion requires two distinct matching independently verified post-activation scheduled receipts; do not count pre-pilot runs, empty passes or manual maintenance.
10. Establish first pilot receipt as the observation baseline. At the first existing hourly pass at/after 24 and 48 elapsed hours, save a cumulative pilot checkpoint and report throughput, first dispositions, six-gate completions and manual-admission yield separately, including zero. Aim for 80 distinct useful dispositions in 24 hours subject to budgets; this is a measurement target, never a quality waiver. Reforecast only from observed eligible yield. No duplicate monitoring/processing schedule is needed.

On any integrity/access/lease/budget violation, retain/revert the five-candidate ceiling, record the exact issue and stop the affected work. Never infer software-capability or permission changes. Unsupported guides/journalism/reports remain explicit holds pending separately verified compatible executors.

> Source recovery execution update (4 November 2026): follow `docs/content_review_source_recovery.md` for the tested source runner, complete blob retrieval, next-gate selection, atomic checkpoints and processing-yield evidence. This is an implementation continuation of the existing hourly bounded pilot, not a new schedule or relaxed admission policy.


## Approved text resources and checkpoint transport (5 November 2026 UTC)

Read `docs/content_review_manual_resources.md` and `docs/content_review_checkpoint_transport.md`. The owner approved manual-only best-practice guides, technical reports and investigative journalism. Those three types are no longer parked for policy approval; use their qualitative route, never paper bibliometrics or automatic acceptance. Other non-paper types retain their existing holds. Exact blob-SHA comparison before the atomic tree write is mandatory; validate stage JSON as well as manifests. A whole-file tool response is not safe checkpoint transport. Preserve the hourly schedule and pilot limits.



## Standing proactive maintenance — 5 November 2026

Read `docs/content_review_proactive_maintenance.md` and `config/content_review_defects.json` every pass. Routine reversible tool/process repairs are part of the existing worker responsibility across all collections, weekly discovery and corpus maintenance. Repeated actionable failures require a concrete repair, bounded diagnostic result, or actionable escalation with exact decision and verification criteria. Preserve the separate independent observer role, actual denials, current authorization and all budgets/leases/checkpoint rules. Zero-attempt passes do not establish recovery. Record each collection's useful progress or evidence-backed deferral.

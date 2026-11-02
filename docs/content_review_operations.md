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

The status panel reads current GitHub contents and workflow runs on every operator Refresh, with no shared response cache and no raw-CDN fallback. Browser auto-refresh is every 30 seconds. Read time, worker activity time and native scheduler observation time are separate. The hosted Site has no direct native Automations read integration; never describe a new GitHub read as a new native scheduler observation.

After native automations.peek and acquiring/readback of the shared lease, BEFORE D1 reconciliation, candidate processing, slow source reads or tests, execute:

```text
python -m tools.content_review.operations --native-observation <actual-native-observation.json> --run-id <actual-native-run-id> --phase start
```

Publish and read back BOTH config/content_review_worker_status.json and config/content_review_operations.json immediately, using the existing SHA guards. The helper records current_run with the actual native started_at, scheduled_for, run ID, observed_at and application state. Do not postpone this first publication until the end of a pass. No candidate attempt is consumed.

During processing, at least once every 60 seconds, fetch the current native observation and repeat with --phase running; publish/read back both files. If execution or publishing is unavailable, preserve the last observation and report the actual blocker. A stopped heartbeat must become visibly degraded; do not keep a stale Running claim. Refresh may display a newly acquired, unexpired scheduled-run lease before its start heartbeat arrives, explicitly labelling that timestamp as lease acquisition rather than native start. Maintenance leases never establish scheduled worker activity.

After writing the actual canonical receipt, execute with --phase complete (or --phase failed for a real application failure), publish/read back both files, and release the lease in finally. Application completion remains separate from native terminal completion; only independently fetched terminal evidence with the exact receipt proves scheduled success. Do not replay processing to update a status label. Preserve current_run when releasing the lease so the console can show the latest completed application state while waiting for independent native confirmation.

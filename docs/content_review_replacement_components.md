# Unattended review replacement: validated components

These components are not a deployed coordinator, scheduler or monitor. The old
automations remain disabled. Do not enable a runner until the owner-private D1
read path, single-writer lease, checkpoints, publication safeguards, bounded
budgets and independent observation have all been integrated and verified.

`tools/content_review/d1_reconcile.py` validates two complete D1 reads, joins
every immutable submission, decision and job, selects the latest completed
revision per owner/collection/batch and matches each active decision to the
same candidate, review number, sealed batch and reviewed-content hash. Missing, changed or
conflicting candidates are held; unknown or malformed data fails closed. The
function does not apply decisions or authorize publication. Its CLI reads one
JSON line on stdin and prints only aggregate counts. Keep raw snapshots and
private identities out of the public repository, logs and workflow inputs.
`d1_reader.cjs` provides a connector-injected, bounded reader that uses only
the exact overview names and connector-provided offsets. It rejects omitted
columns or truncated values, gaps, duplicate identities and changing complete
reads. Its required heartbeat callback must maintain verified liveness while
the separately held remote lease remains valid, including while connector calls
are in flight. The reader itself neither acquires nor renews a lease. It returns private rows
to the caller in memory and never writes or logs them.
`select_reconciled` overlays matching decisions on disposable in-memory copies
before choosing candidates and holds changed or conflicting decisions out of
selection. It does not persist that overlay or acquire the writer lease.
`coordinator.py` makes a five-candidate plan only after validating the current
lease, heartbeat, D1 reads and registry. It lists an explicit disposition for
every registered collection, reports APWG, the corpus audit and Virus Bulletin
as requiring their separate adapters, and sets OpenAlex and paid requests to zero for the plan.
Per-collection matching-decision counts are reconciliation observations, not
processed work. The plan performs no candidate work, network calls or writes.
`source_plan.py` prepares bounded source requests only for candidates selected
after the private decision overlay, exact committed inputs and a current
separate heartbeat. A held DOI candidate does not suppress an eligible peer.
`source_accounting.py` prepares an idempotent request count and receipt only
after independently supplied native workflow and artifact evidence agrees;
`source_request_guard.py` and `source_result_guard.py` prepare two-file atomic
bundles for a single pending request and its later verified receipt. The
pending reservation survives a run transition with its original run identity.
A later run accepts the result only with matching original run and lease history;
it records the original budget use without charging the later run or dispatching
the request again. Missing or inconsistent history holds further source work.
The reported source workflow commit must be an ancestor of the current review
head and contain the exact two-file atomic request reservation; a successful but
unrelated workflow cannot supply a receipt for that request.
The connector writer can save those bundles only after the same live fence. The
outputs still require an atomic leased write and readback; none of these
planning modules dispatches a workflow or makes a provider request.
`apwg_adapter.py` reproduces the Site's filtered APWG candidate IDs, content
hashes and batches for decision reconciliation. APWG execution still needs a
separate source/decision writer; normalization is not processing.
`corpus_audit_adapter.py` classifies matched audit decisions in memory. A
rejection remains a removal-review request, requires the corresponding D1
job and matching original record, and never authorizes deletion. The derived
outcomes are private and must not be logged or committed. Live public target,
lease and D1 checks remain mandatory before any eventual publication action.

`verified_inputs.py` loads registered collection manifests, main-branch public
corpus, exclusions and current queue, and the preserved original weekly queue
from immutable Git blobs. It verifies blob identity and size, the original
queue's SHA-256 and every retained upstream row identity. The caller must still
obtain and recheck the actual remote heads; local objects do not prove freshness.

`duplicate_stage.py` can calculate one local duplicate/exclusion result from
those verified inputs after a D1-aware plan, with no provider calls or writes.
It skips the candidate's own row only within its own collection; the same
identifier in another collection or the public corpus is still checked. APWG,
corpus-audit and Virus Bulletin remain on their separate adapter paths. The
result is not a persisted checkpoint and cannot authorize publication.
`duplicate_checkpoint.py` prepares a candidate manifest, lifecycle record,
stage summary, worker state and new mechanical receipt together. It preserves
prior duplicate evidence, rejects conflicting stage evidence and never writes
the bundle. Its caller must check the receipt path is new, verify the exact
base blobs, re-read D1 and both heads under the live lease, and publish all
files in one expected-head commit. This is not yet a deployed writer.
`checkpoint_guard.py` checks the proposed bundle against the actual immutable
base blobs and tree, requires a new receipt, validates the lease observation
and committed lifecycle policy, and rejects unrelated candidate, stage, worker
or history changes. It still cannot make a remote lease or D1 snapshot atomic;
the caller must perform the required live rechecks and compare-and-swap.
`github_atomic_checkpoint.cjs` adapts that proof to the existing GitHub
connector. It checks the expected head and original file identities, verifies
each created blob, requires a caller-supplied fresh D1/lease/source fence,
uses an expected-head update and reads back the head and blobs. An ambiguous
update must be reconciled rather than retried. `d1_live_fence.cjs` compares
fresh complete D1 snapshots, both branch heads, native state and the verified
lease-bound heartbeat; `d1_fingerprint.cjs` computes the same private digest as
the Python reconciler in memory. The modules still need an actual scheduler
and authenticated connector callbacks, and the D1 read is not a transaction.

Two matching paginated reads are not a database transaction. The coordinator
must take complete fresh reads and recheck their fingerprint and immutable Git
source heads while holding the existing shared writer lease immediately before
each checkpoint or release. A changed, incomplete or unreadable state stops
the affected work. Preserve all prior revisions and decisions; drafts are never
final decisions. All existing publication and hash checks continue to apply.

`lease.py` prepares bounded acquire, renew and release state transitions and
preserves lease history. These pure functions do not acquire a remote lease.
`run_state.py` prepares a run-start observation while preserving the previous
complete current-run record; it refuses to replace a running observation
without retained evidence that the previous lease expired. It performs no write.
`lease_transition.py` prepares start, heartbeat and failure-release state only
for the configured native run. `github_atomic_lease.cjs` can publish and read
back that single state file with an expected-head update. Neither component
installs a scheduler, obtains native evidence, nor guarantees a live heartbeat.
`heartbeat_evidence.py`, `detached_heartbeat.py` and
`github_atomic_heartbeat.cjs` prepare, verify and write liveness on a separate
Git ref, bound to the exact review head and lease. The ref has been created,
but no heartbeat writer is installed or scheduled. `github_read_heartbeat.cjs` independently reads the immutable
heartbeat blob and verifies its Git hash with `git_blob_sha1.cjs` before the
live fence consumes it. Site version 37 can consume that evidence when configured and will
show missing or stale evidence as degraded.
`runtime_guard.py` can use immutable review and heartbeat heads for each
bounded work unit and reads its budget from the committed review policy. The
caller must independently recheck both remote refs; local Git objects alone do
not establish that they are current.
The coordinator must commit with an expected-head comparison and read back the
winning lease before working, renew only while still owner, recheck before
checkpointing, and stop immediately on a conflict or expiration. The heartbeat
helper rejects expired or foreign leases. The local Git compare-and-swap test
does not prove that a live distributed coordinator is installed.

`independent_monitor.py` is a read-only verifier for independently obtained
native run and Git blob evidence. It requires a scheduled native completion,
canonical receipt, matching times and intact, budget-compliant checkpoints;
it reports only candidate gate transitions corroborated by before/after blobs.
`monitor_snapshot.py` prepares a dated observation for distinct configured
worker and observer identities. It is not itself a scheduled observer and its
caller must independently fetch native records and immutable receipt evidence.
Unverified source claims, no-work runs and checkpoint changes alone do not prove
publication or unattended recovery. It fails closed on decision changes unless
they can be separately reconciled. It is not yet an independent scheduled job.

`work_plan.select` rotates across eligible collections before revisiting a
collection, even if another collection has stronger evidence. Within each
collection it prefers supported, more complete evidence. The future coordinator
must persist `source_attempts[collection].at` only after an actual candidate
attempt under the lease, separately from `source_last_progress`, which changes
only when source work actually progresses. A duplicate gate is recorded as an
attempt, not as source-retrieval progress. Passing no attempt history cannot prevent repeated blocked
collections from monopolizing subsequent passes; this change is not yet a
deployed fairness guarantee.

The repository verifier accepts only a native `completed` run with its canonical
receipt path. `no_update`, dispatch, an empty pass and tests do not establish
useful processing. `operations.py` reads the target scheduler identity from the
monitor configuration and archives the previous observation when the target
changes. The private Site's receipt and paused-OpenAlex fixes are deployed;
Site version 37 also follows that configured target without inheriting the old
worker's heartbeat or proof, and labels stored processing counts as reports
rather than independently demonstrated results. Actual replacement scheduler and monitor evidence
remain outstanding.

OpenAlex remains fully paused, including DOI lookups and diagnostics. The
November 7 review time does not authorize resumption, and the unresolved HTTP
429 reconciliation hold remains in force. The registry worker has an explicit
source-level owner-pause gate; a time or policy-file change alone cannot release
it. The generic source worker blocks OpenAlex and DOI resolver/registry hosts
before DNS, robots, redirects or HTTP, while preserving previously retrieved
evidence. Releasing these guards requires explicit owner authorization and
provider reconciliation.

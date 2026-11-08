# Unattended review replacement: validated components

These components do not yet constitute a deployed full hourly coordinator. The
old automations remain disabled. A separate one-time duplicate-only pilot uses
the deployed Site lease, heartbeat and fenced checkpoint routes; its result must
be inspected and reconciled before another attempt. It is not full processing.
Keep the full worker disabled until all collection paths, decision safeguards,
bounded budgets and truthful status have been integrated and verified.

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
before choosing candidates and holds changed, conflicting or superseded
historical decisions out of selection. It does not persist that overlay or
acquire the writer lease.
`coordinator.py` makes a five-candidate plan only after validating the current
lease, heartbeat, D1 reads and registry. It lists an explicit disposition for
every registered collection, reports APWG and the corpus audit as requiring
separate execution adapters, permits Virus Bulletin's duplicate and source
stages, and sets OpenAlex and paid requests to zero for the plan.
Per-collection matching-decision counts are reconciliation observations, not
processed work. Coverage reports due candidates that lack an executor, and
reports a missing lifecycle entry for numbered candidates separately from
unnumbered intake instead of treating either as an empty collection. The plan
performs no candidate work, network calls or writes.
`source_plan.py` prepares bounded source requests only for candidates selected
after the private decision overlay, exact committed inputs and a current
separate heartbeat. A held DOI candidate does not suppress an eligible peer.
`source_accounting.py` prepares an idempotent request count and receipt only
after independently supplied native workflow and artifact evidence agrees;
`source_request_guard.py` and `source_result_guard.py` prepare two-file atomic
bundles for a single pending request and its later verified receipt. The
pending reservation survives a run transition with its original run identity.
A pending source request no longer necessarily consumes every full-coordinator
cycle: the coordinator rotates source discovery, an eligible duplicate gate,
and an eligible retained-source gate, while preserving the original reservation
and run history. A deferred local check falls through to source discovery. This
does not resolve a failed request, process all remaining gates, or establish
fair coverage of every collection.
For a conclusively failed source workflow, a guarded deferral can instead retain
the original request and an unresolved hold for its candidates and known
origins. Provider usage and redirect destinations remain unknown; the source
planner, Site validator and source worker hold all source requests until the
failure is reconciled. Unrelated local duplicate checks can proceed. The Site
and source-worker safeguards are deployed; the coordinating deferral has not
yet been scheduled.
`coordinator_source_pilot_cli.py` runs a controlled source cycle through the
same lease and guarded source stages. It does not turn on the hourly scheduler;
pending or failed source work is not counted as a completed candidate gate.
A later run accepts the result only with matching original run and lease history;
it records the original budget use without charging the later run or dispatching
the request again. Missing or inconsistent history holds further source work.
The reported source workflow commit must be an ancestor of the current review
head and contain the exact two-file atomic request reservation; a successful but
unrelated workflow cannot supply a receipt for that request.
`source_retention.py` prepares retention for one candidate only after rechecking
the committed receipt, original artifact and workflow, candidate hash, current
private decisions, live heartbeat and bounded work window. It neither writes the
manifest nor passes a gate. `source_retention_checkpoint.py` recomputes that
proposal and prepares an immutable checkpoint receipt with the manifest and
unchanged worker state. The connector accepts only those paths and requires the
live fence and readback; the full scheduled coordinator is not yet enabled.
The connector writer can save those bundles only after the same live fence. The
outputs still require an atomic leased write and readback; none of these
planning modules dispatches a workflow or makes a provider request.
Source failures preserve origin cooldowns across runs, including equivalent
host spellings and default ports. SOUPS intake reservations can be checked
without assigning an editorial review number; the independent guards reject
number collisions and existing private review state under the D1 fence.
`apwg_adapter.py` reproduces the Site's filtered APWG candidate IDs, content
hashes and batches for decision reconciliation. APWG execution still needs a
separate source/decision writer; normalization is not processing.
`corpus_audit_adapter.py` classifies matched audit decisions in memory. A
rejection remains a removal-review request, requires the corresponding D1
job and matching original record, and never authorizes deletion. The derived
outcomes are private and must not be logged or committed. Live public target,
lease and D1 checks remain mandatory before any eventual publication action.
`corpus_audit_history.py` additionally binds the earlier 490 removals and 224
keeps to the exact historical request, receipt, completed jobs, reviewed
hashes, historical public blob and main-branch ancestry. It identifies historical
receipts without asserting current public state or authorizing a repeat removal.

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

`github_site_api.cjs` prepares the corresponding Site-hosted GitHub adapter:
all requests go only to `api.github.com` with redirects disabled, and the final
mutation uses GitHub's expected-head atomic commit. It supports at most five
files and 12 MiB of UTF-8 content per commit; its guarded caller checks every
created blob hash and treats ambiguous outcomes as requiring reconciliation. The adapter alone
does not authorize a write and must be used through the existing semantic guard
and live D1/native/lease fence. On November 7 an owner-private Site route sent
a 10,485,773-byte synthetic file in one expected-head mutation to an isolated
probe branch. GitHub independently confirmed commit `2f0279282353ba8d55d4dd00fa5678b7ff363ec1`,
its sole parent, full tree and expected blob. This validates one large synthetic
payload, not a multi-file production checkpoint or candidate processing. The
temporary Site route was removed. The live test also showed that Cloudflare
rejects `redirect: error`; the adapter now uses manual redirects and fails
closed on 3xx responses without forwarding credentials.
The same transport can read the main and heartbeat heads and prepare guarded
lease and heartbeat updates; heartbeat writes are limited to the heartbeat
record on its own ref. The caller must still independently establish the native
run and validate lease transitions against the committed state. No generic
write endpoint has been installed.

`site_d1_reader.cjs` prepares two bounded, complete reads of the three review
tables through the Site's existing database binding, checking schema, counts,
rows and heartbeat between reads. A temporary read-only Site diagnostic on
November 7 verified both reads against the live binding: 70 submissions, 937
decisions and 615 jobs. The diagnostic was removed afterward. This was not a
lease or candidate-processing test. The caller must keep the lease alive during
each database call and perform the final live fence before a GitHub update.
`site_snapshot_service.mjs` provides a bounded, no-store service-only response
for that reader. Site version 57 installed the matching private route after
confirming the owner-only access policy. It relies on owner-private Sites
dispatch to authenticate the service caller, rejects signed-in visitor
requests, and never logs database values or error messages. A live service
request verified both snapshots and the no-store header; an unauthenticated
request was rejected with HTTP 401. The result does not assert a verified lease.
`site_reconcile_client.py` reads this route without persisting private rows,
reconciles the complete snapshots with immutable current Git blobs, and checks
both branch heads again. On November 7 a live read-only run matched all 937
active decisions with no holds. It did not process candidates or acquire a
lease. A separate Site-linked scheduled check also completed this reconciliation
without user action. The scheduler and final live fence still need installation
and testing. Site version 62 retains the route and prevents the retired source
discovery row from reappearing when a replacement target is configured.

`lifecycle_intake.py` prepares at most five additive lifecycle entries for
numbered candidates, rotates across collections, preserves existing entries,
and excludes existing decisions, holds, changed hashes and unnumbered intake.
It creates no attempt, makes no write and confers no publication authority.
Its proposed ledger requires a semantic checkpoint guard, a fresh D1/source
fence and expected-head write before use; those connections do not yet exist.

Two matching paginated reads are not a database transaction. The coordinator
must take complete fresh reads and recheck their fingerprint and immutable Git
source heads while holding the existing shared writer lease immediately before
each checkpoint or release. A changed, incomplete or unreadable state stops
the affected work. Preserve all prior revisions and decisions; drafts are never
final decisions. All existing publication and hash checks continue to apply.

`d1_write_fence.sql` and `d1_write_fence.mjs` prepare an additional database
fence for the interval between the final D1 check and GitHub's atomic update.
SQLite triggers reject inserts, updates and deletes on submissions, decisions
and review jobs while the singleton fence exists. A preparing fence can be
aborted only by its exact owner and operation. Once the GitHub commit begins,
release requires independently checking a single-parent commit with the
expected full tree and receipt blob, and observing the same branch head twice.
An unchanged, moving or unknown head remains locked. `proposed_tree.py`
computes that tree in a temporary Git object store while leaving the repository
index and files untouched; it does not replace semantic validation. This design
can temporarily prevent new decision submissions, potentially until a human
resolves an ambiguous write. It needs a clear retry message and a tested
recovery path. The review branch currently reports `protected: false`, so
force-push safeguards cannot be assumed. Site version 63 installed the
additive fence schema and triggers; the fence was empty after deployment. A
private before/after comparison confirmed all 70 prior submissions, 937 prior
decisions and 615 prior jobs unchanged. The fence is not yet wired to the
worker, and a local test does not close the live cross-system race.
`site_write_fence_migration.sql` mirrors the applied Site migration. It excludes
a duplicate `candidate_assessments` table generated because an older migration
has no Drizzle snapshot. Local D1 migrations and real review submission SQL
passed with existing rows preserved.

`d1_fence_status.mjs` inspects the table, singleton constraints, unique index
and nine trigger definitions without returning owner identities or changing
data. Site version 64 exposed the read-only status and reported nine matching
triggers with no active fence. An idle fence does not establish worker health;
a held fence means review submissions must wait while a checkpoint is verified.
`d1_fence_service.mjs` prepares narrow acquire, begin, abort and confirmed
release operations. It rejects retired targets; before acquisition and commit
it rechecks the current Git heads, recorded worker lease, bound heartbeat and
private D1 fingerprint. It does not write GitHub or independently query the
native scheduler. Its caller must obtain genuine native observations, and the
separate semantic checkpoint writer must still be installed and verified.

`lease.py` prepares bounded acquire, renew and release state transitions and
preserves lease history. These pure functions do not acquire a remote lease.
`run_state.py` prepares a run-start observation while preserving the previous
complete current-run record; it refuses to replace a running observation
without retained evidence that the previous lease expired. It performs no write.
`lease_transition.py` prepares start, heartbeat and failure-release state only
for the configured native run. `github_atomic_lease.cjs` can publish and read
back that single state file with an expected-head update. Neither component
installs a scheduler, obtains native evidence, nor guarantees a live heartbeat.
`run_completion.py` prepares a canonical run receipt and releases the lease
only after revalidating committed mechanical checkpoints, the reviewed hashes,
two current D1 reads, a fresh detached heartbeat and the observed native run.
It records an empty pass as `no_work`, never as successful processing. The
atomic writer supports this two-file completion bundle with the final D1 and
lease fence. The controlled duplicate pilot connects these components for its
limited scope; it does not establish full scheduled recovery.
`heartbeat_evidence.py`, `detached_heartbeat.py` and
`github_atomic_heartbeat.cjs` prepare, verify and write liveness on a separate
Git ref, bound to the exact review head and lease. The private Site provides a
heartbeat writer used by the controlled pilot; the full worker is not scheduled.
`github_read_heartbeat.cjs` independently reads the immutable
heartbeat blob and verifies its Git hash with `git_blob_sha1.cjs` before the
live fence consumes it. The current private Site consumes that evidence when
configured and shows missing or stale evidence as degraded.
`runtime_guard.py` can use immutable review and heartbeat heads for each
bounded work unit and reads its budget from the committed review policy. The
caller must independently recheck both remote refs; local Git objects alone do
not establish that they are current.
The coordinator must commit with an expected-head comparison and read back the
winning lease before working, renew only while still owner, recheck before
checkpointing, and stop immediately on a conflict or expiration. The heartbeat
helper rejects expired or foreign leases. The local Git compare-and-swap test
does not prove that a live distributed coordinator is installed.

The owner retired the separate monitor task. Keep its definitions and history
for reference, but do not schedule it or include it in the review console.
The following dormant code is historical and is not the requested monitoring
architecture. `independent_monitor.py` is a verifier for independently obtained
native run and Git blob evidence. It requires a scheduled native completion,
canonical receipt, matching times and intact, budget-compliant checkpoints;
it reports only candidate gate transitions corroborated by before/after blobs.
`monitor_snapshot.py` prepares a dated observation for distinct configured
worker and observer identities. It is not itself a scheduled observer and its
caller must independently fetch native records and immutable receipt evidence.
`detached_monitor.py` and `github_atomic_monitor.cjs` prepare and write that
observation to a separate monitor ref with native-observer and worker rechecks,
compare-and-swap and readback. The ref and independent schedule are not yet
installed. The console no longer consumes or displays that retired monitor ref.
Unverified source claims, no-work runs and checkpoint changes alone do not prove
publication or unattended recovery. It fails closed on decision changes unless
they can be separately reconciled. It is not yet an independent scheduled job.

`corpus_audit_live_check.py` is a bounded read-only check of receipt-bound
historical corpus decisions, the current D1 overlay and public-catalogue bytes.
It reports aggregate exact-key comparisons only, with private rows kept in
memory. A matching key is not identity proof and a nonmatch is not proof of
absence. It does not change decisions, process candidates, hold a lease or
authorize publication; it is not yet connected to the scheduled coordinator.

`work_plan.select` rotates across eligible collections before revisiting a
collection, even if another collection has stronger evidence. Within each
collection it prefers supported, more complete evidence. The future coordinator
filters for duplicate-due or source-due candidates before its five-candidate ceiling; if all
five are held, it ends that bounded pass and gives source work a later turn
instead of silently inspecting a second set of candidates. A bounded rotation
based on retained run history moves the selection window across a stable due
inventory, including when no checkpoint can be made. It must persist
`source_attempts[collection].at` only after an actual candidate
attempt under the lease, separately from `source_last_progress`, which changes
only when source work actually progresses. A duplicate gate is recorded as an
attempt, not as source-retrieval progress. Dynamic inventories, unavailable
executors and failures still need runtime observation; this change is not yet a
deployed fairness guarantee.

The retained-source gate selects only candidates with a hash-matched source
receipt before applying its five-candidate ceiling. A separately held source
request does not block local evaluation of an unrelated retained receipt; the
Site still rechecks its original artifact and private decisions before writing.
Its format path is deliberately narrow: matching publisher bibliographic
metadata must explicitly identify a research article, and conflicting document
types are held. It does not infer research-paper format from a PDF or page
alone, and this path remains unverified in a scheduled live run.

The planner reports quality, classification and admission work as requiring a
separate executor until guarded paths exist; those candidates cannot consume
the bounded slots for executable duplicate or source work. The Python and Site
quality-hold rules independently identify a narrow zero-core-term condition,
but only as a provisional hold with no score or gate pass. Existing quality
evidence is held for reconciliation rather than repeated. These rules are not
connected to a writer or scheduler.

The repository verifier accepts only a native `completed` run with its canonical
receipt path. `no_update`, dispatch, an empty pass and tests do not establish
useful processing. `operations.py` reads the target scheduler identity from the
monitor configuration and archives the previous observation when the target
changes. The private Site's receipt and paused-OpenAlex fixes are deployed;
Site version 39 also follows that configured target without inheriting the old
worker's heartbeat or proof, and labels stored processing counts as reports
rather than independently demonstrated results. A native result requiring
action or reporting failure cannot verify a receipt. Native scheduled-completion
evidence remains incomplete. The current Site also displays the configured worker's
limited scope rather than presenting a duplicate-only pilot as the full worker.

On November 7 the owner explicitly released the OpenAlex pause and authorized
overriding the unresolved 429 reconciliation hold without verified provider
reset evidence. Preserve the old pause and hold in policy history. Enforce
the current main policy, existing cooldowns, 60-second review-worker pacing,
one registry request per review run and the pipeline's bounded request budget.
Generic source retrieval must not bypass these controls: it routes OpenAlex to
the dedicated registry worker rather than sending it through the generic
source transport. Other DOI resolvers are no longer subject to the owner pause.

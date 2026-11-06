# Weekly discovery: OpenAlex access and recovery

Updated 2026-11-05 after explicit owner approval of PR118. Applies to `python -m alex.cli discover`, the weekly
`pipeline.yml` discovery stage and the manual `discover.yml` stage.

## Provider rules and endpoint choice

Current primary sources, checked 2026-11-02:

- https://help.openalex.org/api/authentication/
- https://help.openalex.org/api/get-single-entities/
- https://help.openalex.org/api/errors/
- https://help.openalex.org/access/example-costs/

OpenAlex documents singleton work retrieval by DOI as free, including
`GET /works/https://doi.org/<doi>`. Searches and list/filter requests consume
the account's usage budget. Its current free-key ceiling is 30 requests per
second; special heavy queries have lower ceilings. These are ceilings, not
targets. The owner-approved recovery pace is one serial OpenAlex call per second,
with a 20-second request timeout and no automatic OpenAlex retries. The prior
60-second diagnostic pace completed20 successful calls; the final response
reported9,800 credits remaining. This observation does not guarantee future allowance.

Free singletons are an endpoint on the same API, not an independently authorized
request channel. The documentation does not promise an independent rate-limit
or cooldown pool for DOI retrieval. Keep the same key, pacing, request cap and
provider hold across search, list/filter and singleton calls. Conservatively
pause singletons too when the client observes exhausted account allowance.
Never rotate keys, remove authentication, change runners or switch endpoints
to evade a restriction. No prepaid spending or paid plan is enabled by this change.

Individual DOI lookups now use the singleton endpoint. Bulk helper callers
deduplicate DOIs, resolve them individually, and stop the loop after a provider
failure. A singleton 404 is a completed lookup with no matching record; it is
not an accepted paper or a reason to relax quality requirements.

## Limits and coverage

`config/weekly_discovery_policy.json` sets each discovery pass to at most:

- 2,700 seconds (45 minutes) of discovery runtime;
- 300 HTTP client send attempts across sources, including retries;
- 250 OpenAlex send attempts shared by searches and singleton lookups.

Before an OpenAlex pacing wait, both the wait and its bounded request must fit
inside the remaining runtime. Other requests use the remaining timeout budget.
Each pass retains its45-minute limit. The repository-owned controller has a
four-hour total deadline, and its GitHub job has a five-hour ceiling for startup,
state publication and diagnostic artifact upload. Requests timeouts are connect/read timeouts, not an absolute
guarantee against a continually trickling response. Git/network state pushes
are bounded at 120 seconds each; exceptional runner termination remains possible.

The existing per-query pagination ceilings and all relevance/quality thresholds
are unchanged. Complete means the configured bounded search/enrichment work
finished; it does not claim exhaustive coverage of every paper at every source.
Disabled sources retain their existing gates. Available independent sources
can progress even when OpenAlex is held or has exhausted its per-pass budget.

## Checkpoints and resumption

`data/discovery_checkpoint.json` stores the original date window and query
registry, completed task results and successful request responses. A resumed
pass replays completed pages/tasks without sending those requests again, then
continues unfinished work. Failed responses are not saved as successful pages.
Corrupt state fails closed; never replace it with an empty checkpoint.

Candidates are written atomically after each query and before enrichment.
Title deduplication preserves the existing candidate identities. DOI enrichment
includes this window's previously saved candidates. Its task identity depends
on the missing DOI set, so new arrivals on resume cannot inherit an older
"enrichment complete" result. Singleton responses already obtained are reused.

An unfinished window keeps its original dates across later passes. Once it
finishes, the next window overlaps the last completed boundary and covers any
gap rather than skipping the intervening dates.

State, receipt and OpenAlex pacing files travel with candidates through the
existing gzipped `pipeline-state` branch and its compare-and-swap push. In
GitHub Actions, successful-response boundaries publish state at most once every
120 seconds, plus a final forced push. This bounds recoverable remote progress;
an abrupt host loss can still lose work since the last successful push. A failed
state push stops new network work instead of overwriting another writer.

`ALEX_OPENALEX_STATE_PATH=data/discovery_openalex_state.json` is inherited by
all weekly pipeline stages and the manual discovery workflow. It preserves
observed pacing/cooldown across their state pulls. This is not a distributed
account-wide governor for unrelated runners or the separate Content Review
service. Those must continue their own conservative limits and shared provider
policy. Do not claim a verified aggregate account allowance without provider
usage evidence.

## Failures, receipts and downstream publication

429, 5xx, authentication failures and connection/timeout errors stop OpenAlex
for the rest of that client pass. Persist the cooldown using the longer of
Retry-After, the configured cooldown and any exhausted-quota reset header.
All OpenAlex endpoint types honor it. Do not spend the rest of a pass iterating
hundreds of requests that cannot be sent. Deferred tasks are retried on a later
authorized bounded pass after the hold permits. The GitHub controller described
below may perform one such cooldown resumption; the HTTP client never retries
the failed request automatically.

`data/discovery_run_receipt.json` records:

- `complete`: all configured tasks completed, including empty successful results;
- `partial`: some tasks completed while others remain deferred or failed;
- `deferred`: no task completed because runtime/request/provider limits blocked work;
- `failed`: no task completed and an application/request failure prevented progress.

Receipts include actual client send-attempt counts (cache/hold checks excluded),
endpoint types, HTTP status or exception class, UTC timestamps, duration, and
numeric allowlisted quota/reset/Retry-After headers when supplied. Secrets,
authorization headers, exception URLs and request query strings are excluded.
Counts are client send attempts; automatic HTTP redirects are not separately
instrumented as additional sends. Missing headers mean unknown allowance,
not unlimited allowance. Do not infer successful collection from scheduler
dispatch, a source returning no new papers, or a previous receipt.

Partial/deferred/failed discovery exits nonzero **after saving state**. Workflows
push that state even on a nonzero discovery exit and write coverage status to
the GitHub step summary. The pipeline's existing dependency chain blocks
classification/publication until discovery returns complete. The existing report
job remains responsible for the GitHub failure issue. No review decisions,
accepted corpus files or quality thresholds are changed by this recovery logic.

## Verification and live limits

Run mocked regression coverage for singleton routing, shared search/DOI caps,
cooldown persistence, zero allowance, runtime guards, request-page replay,
new candidates after resume, corrupt state, credential-safe receipts and
state-push failure. No live provider traffic is needed for those tests.

After deployment, an authorized live pass is still required to verify actual
provider availability, account allowance and the GitHub state-push path. Inspect
the fresh receipt and state commit; a partial result is useful preserved progress,
not a completed weekly collection. Never rerun an old workflow definition when
verifying changed workflow wiring; start a fresh workflow from the updated branch.


Owner-approved recovery continuation (5 November): PR118 replaces the temporary
20-call/60-second diagnostic limits following explicit approval. Resume the
verified saved window from pipeline-state in bounded current-main passes. Keep
300 total attempts,45 minutes, durable checkpoints and all existing downstream
completeness/quality/editorial gates. No new schedule, paid plan, credential
rotation or automatic provider-error retry is enabled. Observe each terminal
receipt before launching another pass; never overlap active pipeline writers.


## Repository-owned continuation — owner approved 6 November

The owner approved moving bounded recovery out of the failing ChatGPT task
handoff. Both existing discovery workflows now invoke
`python -m alex.pipelines.discovery_recovery` inside their shared `pipeline`
concurrency group. No recurring schedule, API key or provider endpoint is added.
The weekly schedule and downstream dependency graph are unchanged.

`config/weekly_recovery_policy.json` limits one invocation to six passes,
four hours total including waits, at most one cooldown resumption, and at most
one hour waiting for provider cooldown. Every pass retains at most250 OpenAlex
requests,300 total attempts,45 minutes,20-second request timeout and serial
pacing of at least one second. The controller only shortens a pass to fit the
remaining overall time. The five-hour GitHub ceiling leaves room for startup,
state pushes, child termination and diagnostic artifacts.

A pass ending only at a request/runtime budget may resume after durable progress
is verified and pushed. A transient provider failure may resume once after the
longest persisted/configured cooldown, if that wait fits the remaining limits.
401/403, exhausted quota, invalid or missing evidence, state-write conflicts,
unknown exceptions, interrupted children and budget exhaustion without progress
stop the controller. Longer holds remain held for a later authorized invocation;
no attempt is made to override them. A timed-out child process group is stopped
before returning, so it cannot overlap a later pass.

Every invocation is keyed by GitHub run ID and attempt. Every child pass has a
unique identity in both its discovery receipt and checkpoint. The controller
checks the identity, window, saved response/task counts, exit status and request
limits. A stale receipt cannot stand in for a failed new pass. A nonzero exit
never releases downstream stages, even if the receipt says complete. Replaying
an already-recorded invocation is refused pending reconciliation.

`discovery_recovery_receipt.json` retains each pass's complete request receipt;
`discovery_recovery_ledger.json` retains invocation/pass summaries and hashes
across later runs. Both travel atomically with the existing pipeline-state files.
Each pass is recorded before work and after verified completion. The existing
Git compare-and-swap state push rejects competing writers; a failed push stops
new requests and is never blindly retried. Native artifacts preserve receipts
and startup diagnostics even when discovery fails. The existing report job
exposes terminal failures. A stopped or partial controller remains nonzero;
publication still requires complete discovery and every downstream stage.

Tests exercise an actual three-DOI discovery across a two-request cap: the
second pass makes only the one unresolved request and retains all three recovered
abstracts. Controlled tests cover interrupted work, cooldown waiting, access and
quota denials, corrupt/stale receipts, state conflicts, no progress, finite limits
and subprocess termination. These tests establish mechanism behavior; live
unattended evidence is reported separately. Comprehensive project QA remains a
separate phase after recovery is established.


## Downstream provider serialization

Non-OpenAlex HTTP calls share a per-host lock across client instances in the
same process, covering the retry sequence and half-second polite delay. This
prevents parallel candidate workers from overlapping requests to Crossref,
Zenodo or another single source. Independent hosts can still overlap. A queued
worker rechecks its client's provider hold after acquiring the lock. Existing
retry limits are unchanged; OpenAlex continues through its stricter persisted
serial governor. This in-process lock does not coordinate unrelated runners.

Citation-chain and harvest workflows persist the shared OpenAlex governor back
to pipeline-state even if stage processing fails, provided the initial state
pull succeeded. Standalone workflows use the same state path and concurrency
group. A failed state push fails the stage, preventing dependent jobs from
starting with an older hold. Forced runner termination may still prevent cleanup.

## Explicit reconciliation of a completed receipt

The manual pipeline input `resume_completed_discovery_run` names a prior native
run whose completed discovery was rejected solely by the old floating-point
runtime receipt defect. The controller validates the prior blocked invocation,
final pass identity, complete checkpoint, counts, original window and successful
request outcomes before writing. Only the immediately adjacent floating-point
value above the configured runtime is eligible; actual elapsed time must remain
within that limit. Other failures and genuine overruns remain blocked.

This mode preserves the prior controller and final request receipt, with hashes,
in the new recovery evidence. It replays the exact completed window once with
both HTTP request budgets set to zero. Cached tasks and responses remain usable;
any missing response fails without a send. A fresh verified complete receipt is
required to release downstream jobs. Scheduled discovery remains unchanged and
continues to open the next window normally. This is operator reconciliation of
completed work, not a general retry or permission to bypass provider holds.

## Paid classification failure and recovery

Missing OpenAI credentials, network errors, non-success responses, empty output
and invalid schema results fail classification. They never synthesize an `Other`
label. A valid returned `Other` classification remains a legitimate taxonomy
value; all ordinary quality and editorial rules still apply.

`data/classification_request_ledger.json` retains actual response JSON, its hash,
and the digest of the exact model, prompt, schema and input request. Only matching,
hash-verified, schema-valid results are reused, including when credentials are
temporarily unavailable. Reuse sends no request and adds no token usage. Duplicate
concurrent requests share one result. Older corpus labels without this evidence
are not silently treated as verified paid receipts.

Before any paid call, the whole work set is reserved in pipeline-state. Each
outcome is saved locally, with remote checkpoints at most120 seconds apart and a
forced final write. Any known error stops new sends, cancels queued work, waits
for in-flight calls to finish, preserves their actual outcomes and blocks corpus
publication. A failed state write also stops new sends without blindly retrying
that write. Standalone classification uses the same state path and shared pipeline
concurrency. Current workflows retain the ledger as an always-uploaded artifact.

An abruptly killed runner can lose responses since its last remote checkpoint.
Those reserved or started requests are ambiguous, not known unsent: the next
invocation holds them for reconciliation instead of charging again. Only a final
checkpoint after all threads terminate can mark untouched requests `not_sent`.
Received failures and invalid paid responses also remain explicit holds. Never
delete those entries or change their hashes to force a retry. Live publication
and unattended scheduled operation remain separately verified outcomes.

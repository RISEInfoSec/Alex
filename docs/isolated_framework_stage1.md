# ALEX isolated framework stage 1

17 November 2026. **Partial result. Stage 1 has not passed.** The complete
synthetic processing path passes locally. Complete production database recovery
and a genuine unattended staging execution remain blocked. Production migration,
provider collection and further rebuild work are outside this authorization.

## Verified starting point

The actual repository is `RISEInfoSec/Alex`, verified using its Git remote,
local objects and the GitHub API. Work uses the dedicated branch
`codex/isolated-framework-stage1-20261117` and a separate worktree. The verified
main base is `4ae37fe691a770da5650c3de2419d53f80714f81`; the retained local
`origin/main` was older, so it was not used as the authority for the base or
backup. The existing worktree and synced sources were not edited.

Current API reads still match the assessment's main, review branch and
pipeline-state heads. The hosted review and relay remain versions 241 and 5,
with environment revisions 11 and 1, and successful recorded deployments.
Their deployment success does not establish processing success.

The pinned public JSON has 3,283 records and 3,283 unique IDs. The accepted CSV
has 3,288 rows; the exclusion registry has 504 entries; relevance feedback has
714 examples; the metadata hold registry has five entries. These counts were
read from hash-verified snapshots. The public live HTTP endpoint was not
rechecked from this network-restricted executor.

## Results and evidence

| Gate | Observed result | Status |
| --- | --- | --- |
| Git data preservation | Independent snapshots of main, review and pipeline-state restored; all 1,530 file sizes, SHA-256 hashes and Git blob identities match. All compressed files passed complete decompression/CRC checks. Main history bundle verified, cloned and passed `git fsck --full` at the correct base. Snapshot restore took 3.589 seconds on this executor. | Pass for this subset |
| Production recovery | Live review inventory exposes 31 D1 tables. The reader supplies bounded rows without a snapshot or arbitrary schema SQL; it cannot establish complete values, indexes, triggers or consistent cross-table counts. Production D1 has not been exported or restored. | Blocked |
| Hosted source preservation | Version/source/archive identifiers and non-secret environment metadata were inventoried privately. Returned archive references could not be downloaded. The official source helper reached a CONNECT 403 for the hosted Git origin. Full hosted source/history and secrets are not preserved by the GitHub snapshots. | Blocked |
| Complete fixture path | Discovery, ingestion, deduplication, five content-bound checks, explicit synthetic editorial review and preview JSON/CSV. Three candidates, three decisions and one publication; rejected and held items stay unpublished. Three complete replays add no candidates, jobs, decisions or publications. | Pass locally |
| Interrupted worker | A subprocess claims the preview job after approval, is killed with SIGKILL, then a new worker reclaims its expired lease. The original decision remains and exactly one publication is committed. Superseded leases cannot complete; exhausted jobs remain explicit failures. | Pass locally |
| Recovery mechanism | Consistent SQLite backup restored with per-table counts/hashes, schema, indexes, triggers and foreign-key checks. Tests include long Unicode annotations and binary values, plus altered-export rejection. The separate three-candidate fixture database also restored successfully. | Pass on local fixtures only |
| Actual scheduled staging execution | A systemd job and timer are prepared. This managed executor has no systemd runtime or provisioned persistent job host. No staging timer was installed, no scheduled job ran, and there is no native staging scheduler run ID, journal or scheduled database effect. The old production trigger still reports `worker_not_confirmed`. | Blocked |

The targeted suite has **14 passing tests**. See `tests/test_stage1_framework.py`.
The scheduler wrapper test supplies a synthetic invocation ID; it is not a
scheduled invocation. Neither these tests nor mocked check results verify live
providers, production quality thresholds, deployed authentication or D1 concurrency.

Private recovery materials are stored separately from this repository. The
private archive inventory explicitly lists missing production components. Git
review/pipeline exports are current snapshots; their complete branch histories
are not claimed. Public test data contains only synthetic records.

## Architecture decision

`stage1/engine.py` uses one SQLite authority for candidate identities, source
receipts, content hashes, durable jobs, append-only attempt events, required
checks, editorial decisions and publication intent. Transactions commit each
local stage and its next job together. A publication trigger requires the exact
approved content and all five passing checks. JSON/CSV are rebuildable preview
projections; the transactional publication table is authoritative.

Each job has a bounded lease and a token that fences stale workers. Three
expired attempts stop that job without retiring the candidate or discarding its
decision. This is safe for local mocked work. It does not promise exactly-once
paid requests: future external effects need reservation, response retention and
ambiguous-outcome reconciliation before retry.

The framework reuses ALEX's existing exclusion and DOI/title/year normalization.
A source landing page alone is not a candidate identity, so distinct FIRST
papers sharing that page remain distinct. Identity or content conflicts fail
without inheriting approval. Exact received content is retained. Year-only
publication dates stay year-only. Existing exclusions cause a hold before
checks. Missing or malformed fixture check evidence causes a hold.

The fixture check names are metadata, access, format, relevance and quality.
They require explicit evidence for the exact candidate content hash. These are
mocked contracts, not replacement implementations of the existing quality
rules. `stage1/fixture.py` supplies explicit, visibly synthetic human decisions;
the worker does not decide real editorial outcomes. There is no HTTP client,
production publisher or credential acquisition in this package.

SQLite plus a persistent single-host systemd timer is the minimal candidate
runtime. It still needs a real host and observation. No choice of production
platform is settled by this local implementation. A multi-host deployment would
require a suitable transactional database and new concurrency verification.

## Reproduce without production access

Use Python 3.10 or later from the repository root. The framework uses the
standard library and the existing lightweight normalization module; its tests
need pytest. Preserve existing environments and use the installed project
interpreter when available. No package or credential changes were needed here.

```sh
python -m pytest -q tests/test_stage1_framework.py
python -m stage1.fixture \
  --database /private/staging/private/state.sqlite \
  --preview /private/staging/preview \
  --evidence /private/staging/fixture-evidence.json
```

Choose a new private staging directory outside any synced `sources/` tree and
the public checkout. Do not point this command at a production database. The
command is replayable and emits explicit `false` fields for production recovery,
live provider and scheduled-execution verification.

`stage1/recovery.py` exposes `backup(source_path, new_backup_directory)` and
`restore(sql_path, manifest_path, new_database_path)`. Backup uses SQLite's
consistent backup API, then exports full SQL from that snapshot. Restore
requires the matching export digest and source snapshot manifest. A source
manifest derived only after importing an unknown export is not proof that the
original production database was fully exported. App-level relationship checks
must supplement foreign keys when the source schema does not declare them.

Before remote branch creation, all 24 workflow definitions at the pinned main
were inspected. Every push trigger and the Pages workflow-run trigger are
restricted to main; no create, repository-dispatch or pull-request-target
trigger exists there. The remote workflow registry lists 37 current/historical
entries; entries whose definitions are absent from this branch cannot be
triggered by its push. No workflow files were changed. The branch is saved
without opening a PR or manually dispatching workflows.

## Finish the remaining stage 1 gates

1. Obtain a supported, complete consistent D1 export from the hosting owner or
   administrator. It must include all review tables and complete values, schema,
   indexes and triggers, with source-snapshot counts/digests or equivalent
   integrity evidence. The current Sites reader does not supply this capability.
   A hosting-account D1 export facility or owner-provided complete export is
   needed; more GitHub repository permission does not solve it.
2. Restore that export in isolation and compare per-table counts and complete
   value hashes, schema objects and application decision/content/identity links.
   Preserve annotations, submissions, exclusions and provenance. Inventory
   credentials by owner and recovery procedure, without exposing their values.
3. Retrieve hosted review/relay source archives and needed history through the
   host's supported export or an executor with authorized access to its source
   origin. Do not redeploy production to add an export route.
4. Identify an existing persistent isolated runner with no additional charges.
   The prepared `stage1/deploy/` units expect a pinned checkout at
   `/opt/alex-stage1` and a persistent systemd StateDirectory. They deny network
   access and never acquire production credentials. They are templates, not an
   installed service. If no such resource is available, choose the host before
   doing more integration work.
5. On that staging host, install the fixture-only units and enable the timer;
   let a genuine timer occurrence execute with the chat closed. Capture the
   native timer trigger time, service invocation ID, journal, exit status and
   matching per-invocation receipt/database changes. The first run should show
   ten completed stage jobs and one preview publication. Later replays must be
   reported separately as zero-work. Disable this test timer after obtaining the
   evidence. A manual service start, receipt alone or HTTP success is insufficient.
6. Reconcile the evidence and request the owner's decision. Do not migrate
   production or start unrestricted source collection under Stage 1 authority.

Non-secret setup is retained here and in the existing owner-private ALEX setup
runbook. The retained Sites helper passed syntax validation; authentication and
network permissions remain separate. Supported API reads worked for GitHub;
ordinary Git transport to GitHub and the hosted source origin were denied by
this executor's enforced host policy. No credential replacement or policy
bypass was attempted.

## Remaining scope and estimate

Conditional on complete export access and an existing persistent runner, allow
**6–12 additional active engineering hours** to close Stage 1: approximately
3–6 for full preservation/relationship verification, 2–4 for deployment and
native scheduled evidence, and 1–2 for reconciliation and handoff. Hosting
support and access lead time are additional and currently unbounded.

For the remaining replacement after a successful feasibility decision, revise
the planning allowance to **55–105 active engineering hours**, plus 48–72 hours
of unattended observation. This includes the outstanding Stage 1 work. The
local skeleton reduces uncertainty around transactional lifecycle and replay;
it has not reduced the major live integration and recovery risks. Remaining
work comprises production-grade required checks and external-effect recovery,
adapter contracts for the existing sources, reviewer and preview integration,
stable-identity migration mappings, selective editorial restoration, and a
separately authorized cutover/fallback rehearsal. It is not authorized here.

**Recommendation: pause integration until full database export and an isolated
durable runner are available.** Continue with the architecture if those gates
can be demonstrated within the remaining feasibility budget. If the host cannot
provide complete recovery, change the hosting/export arrangement before further
rebuild work. The present evidence does not justify migration or a wholesale
interface rewrite. No Stage 1 background task has been started.

## Work accounting

The instrumented work window started at 10:49:29 and reached this handoff checkpoint at 11:05:32 America/Toronto on 17 November 2026 (16.1 minutes of observed session elapsed time). Opening source reads preceded that timer. This is not a claim of billable human engineering hours. The 8–12-hour ceiling was not exhausted; useful independent Stage 1 work is complete and the remaining gates require unavailable capabilities. Saving and verifying the handoff follow this checkpoint.

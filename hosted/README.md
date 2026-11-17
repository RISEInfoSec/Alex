# Hosted staging integration

This directory ports the recorded-input Stage 2 lifecycle to a Cloudflare
Worker and D1, with an owner-private Sites review interface. The Python
implementation at `7e87077a0d4f13eb0b062829f9bea2d9dc25a9d0` remains the
reference. The archived fixture run and the source-adapter trial use separate
tables and evidence. The trial has one explicitly bounded live operation.

## Build and verification

From this directory, with Node 22 or later:

```sh
npm ci
node build.mjs
node --test --test-force-exit tests/runtime.test.mjs
```

The lifecycle tests compare six normalized source records and all five computed
checks with actual Python reference results, exercise 48 scoring combinations,
parse a retained PDF in the compiled Worker without outbound access, and run
the D1 processing, review, interrupted lease, stale-token and preview paths.
Local lease expiration is controlled by the test; live scheduled recovery
requires separately retained native Cron and D1 receipts.

The compiled source tests submit retained fixtures to the private service,
replay them without duplicate records, and exercise the one-attempt pilot
using a mocked outbound service. Source parse failures and incomplete records
remain visible. The six named-collection cases exercise item-level citation
metadata and keep document type under review. Archive layouts and other
real-world response formats require their own captures and verification.

`data/scenario.json` contains synthetic raw source and document captures.
`golden.json`, `scoring-golden.json` and `pdf-golden.json` contain test-only
Python reference outputs. Runtime checks compute their own results. Policy,
Unicode case folding and standard PDF fonts are bundled so processing does
not require remote downloads. `build.mjs` fingerprints the core, dependencies
and runtime data. A changed implementation cannot silently resume an old run.

## Deployment and identity

Use the supported Sites source and artifact workflow. Keep its project ID in
the private checkout's `.openai/hosting.json`, and place `SCHEDULER_KEY` in
Sites runtime secret settings. D1 binding is `DB`; schema changes use generated
Drizzle migrations. Never modify an applied migration or execute DDL in a
request handler. The initial migration includes immutable-evidence and
publication-gate triggers.

`scheduler.mjs` is a separate account-owned scheduled Worker. Its secret
bindings are `SITE_ACCESS` (native Sites service access) and `SCHEDULER_KEY`.
It has no HTTP handler. Disable workers.dev and version preview URLs before
arming its temporary minute Cron; cap CPU at 1,000 ms. Never put these secret
values in source, files, logs or evidence archives.

The scheduler can process saved fixtures but cannot record owner review
decisions. Review requires the platform-injected signed-in user identity on
the owner-private Site, a same-origin POST and the current content/policy
version. Service bearer access does not establish browser identity.

## Bounded rehearsal and cleanup

The run allows six jobs per tick, at most 40 ticks, and one hour from its first
tick. Jobs have 45-second leases and at most three claims. Five candidates
produce 25 computed checks; a sixth source record remains held for an unknown
publication year. Owner review can apply the displayed five-decision fixture
plan. Only all-pass content can be approved.

After approval, one scheduled occurrence deliberately leaves the preview job
claimed and throws an intentional handler exception. A later genuine Cron
must recover the expired lease, reject the stale token, retain the approval,
produce one publication and verify three replays without duplicate rows.
This tests an abandoned lease and scheduled-handler failure; it does not claim
to SIGKILL Cloudflare's infrastructure. Preview files and their current pointer
are written in one D1 transaction and their hashes are checked on read.

Remove the temporary Cron after collecting matching native scheduled events
and D1 receipts. Preserve the Site, immutable run evidence and disabled
scheduler for inspection. A completed rehearsal does not release the held
source outcome, editorial decisions, provider restrictions, paid-request
holds or production cutover gates.

## Source capture and Crossref pilot

Owner-private Site service access requires the Sites bearer and the staging key.
Send an existing hash-bound recorded capture to `POST /api/source-captures`.
Authentic signed-in owners can inspect the downstream report at
`GET /api/source-captures/<id>`. Adapter evidence stays separate from the
Stage 3 review decisions and publication preview.

`GET /api/source-pilot/crossref` reads the budget and outcome. The authorized
empty POST reserves one attempt before requesting a single existing public DOI
from Crossref. The ledger retains the status, bounded response bytes and
allowlisted headers. It sends no redirects, retries, paid requests or document
fetches. A missing outcome holds the reservation. A successful locator response
goes through the retained capture parser and mechanical checks. An existing
public identity stays held, with no new acceptance or publication.

# ALEX read only recovery export candidate

17 November 2026. **Offline candidate only. No production route has been added,
no Site version has been deployed, and no production database has been exported.**

OpenAI support directed the owner to implement an application-level export.
The [Sites help article](https://help.openai.com/en/articles/20001339-creating-and-using-chatgpt-sites)
confirms that version restoration restores code rather than the database, and
that Sites has no built-in combined database/file backup and restore workflow.
The owner has also inspected the database viewer; no export control was visible.

## Proposed bounded change

Integrate `stage1/recovery_export.mjs` into the exact deployed private review
Site source as a new owner-only recovery download route. Reuse the Site's
existing trusted server-side owner authentication. The `authorizedOwner` boolean
in this library is an integration boundary, **not an authentication mechanism**;
it must never be taken from request parameters or untrusted headers. No route or
authentication integration is supplied or claimed by this candidate.

The handler would serve a private download containing the SQL and manifest.
It would use `Cache-Control: no-store`, expose no public/CORS access, and avoid
logging database content or credentials. Missing or failed owner authentication
would deny access before querying the database. Error responses must be generic.

The change would not add migrations, update database records, modify existing
application routes, change permissions/credentials/schedules, release provider
holds, or perform provider requests. Generating SQL INSERT/DELETE statements in
the downloaded file does not execute them against production. The only SQL sent
by this module to the source is read queries. Reads still consume resources and
can delay concurrent database work; zero operational impact is not promised.

## Snapshot and restoration contract

The library first discovers schema and columns, then reads those definitions
again with every table's data in **one database batch**. If the definitions have
changed, it rejects the result. Cloudflare documents
[D1 batches as transactions](https://developers.cloudflare.com/d1/worker-api/d1-database/#batch).
This is the intended snapshot mechanism; real D1 consistency and resource limits
still need to be verified in isolation before production use. Separate paged
table requests are deliberately unsupported.

SQLite produces typed SQL values before they reach JavaScript. This preserves
large 64-bit integers without JavaScript-number rounding, binary values, long
text and embedded NUL characters. Schema includes user tables, explicit indexes,
views and triggers. AUTOINCREMENT high-water marks are retained separately.
On restoration, triggers are installed after rows so they do not create extra
audit events during the import.

The manifest records schema and SQL hashes and per-table row counts and insert
statement hashes. Those are acquisition integrity records. Acceptance also
requires restoring into a new isolated database, comparing the decoded source
values/types, schema objects, counts and application relationships, and retaining
the original immutable export privately.

The initial bounds are 40 user tables, 10,000 rows per table, 512 KiB per encoded
row and 8 MiB total SQL. A failed query, changed schema, exceeded bound or partial
result fails the whole export. The module rejects virtual tables, generated or
hidden columns, and tables lacking an explicit primary key rather than silently
omitting information. Implicit row IDs for tables with a non-integer primary
key are not preserved: source code must be audited for such dependencies. These
conditions may block this candidate on the real schema; they must not be relaxed
by truncating values or dropping tables. Cloudflare's alpha-only `dump()` API is
not used, and a D1 session bookmark is not treated as a frozen snapshot.

## Verification completed

The Node tests use real SQLite through a D1-shaped adapter, with query-only mode
enforced while each source statement executes. They cover full text with Unicode
and NULs, binary values, int64 precision, real values, schema/index/trigger
restoration, foreign-key relationships, no duplicated audit events during
restore, AUTOINCREMENT continuation, owner denial before database access, schema
changes between discovery and capture, and explicit size/layout failures.

Run with Node 24 or later:

```sh
node --no-warnings --test tests/test_stage1_recovery_export.mjs
```

These tests do not establish actual D1 deployment, SQL-feature compatibility,
all-table recovery, trusted owner authentication or successful production export.

## Requirements before any deployment approval

1. Retrieve the exact deployed private Site source. The retained executor's
   network policy currently denies its hosted Git origin; full source archive
   downloads also failed. Resolve supported source access before editing or
   rebuilding the Site. Do not substitute the public ALEX repository or an older
   hosted source version.
2. Inventory the real schema against the candidate's supported layouts and
   bounds. Prove the D1 batch, table-valued PRAGMA queries, value encoding and
   restore verification on an isolated binding. No live source reads have been
   made using this module.
3. Integrate the existing owner guard and test unauthorized access, no caching,
   no disclosure through errors/logs, and a private download. Keep the hosting
   manifest, dependencies, migrations and existing routes unchanged; verify the
   deployment diff and exact source/build provenance.
4. Present the deployable patch and evidence for the owner's decision. The
   original Stage 1 instruction prohibits changing production code and
   deployments. Support's suggested endpoint does not override that instruction.
   Deployment needs a narrowly authorized exception for the export route and its
   eventual removal. Approval has not been requested or obtained here because
   the integration is not yet deployment-ready.
5. If approved, acquire one private snapshot, restore it independently and verify
   it before claiming the preservation gate passed. Do not put the export or
   annotations into the public repository. Remove the route only under the same
   approved scope and preserve the verified recovery material.

The new Cloudflare Free staging account is independent of this existing
Sites-owned database. Creating it does not grant access to the old database.
Source access, deployment authorization and recovery verification remain
separate dependencies. No background export or deployment task has been started.

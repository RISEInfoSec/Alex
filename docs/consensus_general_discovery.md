# Consensus general discovery routing — 3 November 2026

Consensus is an academic discovery intermediary, not a named collection. Preserve
collection_source and discovery_source as historical provenance; authors, venue,
publisher, DOI, source URL, candidate identity, content hashes, review decisions,
reservations, duplicate keys and publication gates retain their existing meaning.
Future Consensus candidates use collection_id=weekly and the existing general
inventory, deduplication, preflight, review and publication path. Never register
Consensus in review_console.json or a public collection profile. The public
renderer excludes its provenance from both profiled and unprofiled source groups.

Dependency check: main public/accepted corpus contains 3,190 records and zero
Consensus-attributed records. The review-branch Consensus manifest has zero ready
and zero held records; the 176-record weekly manifest and 3,529-record discovery
inventory have zero Consensus candidates. All 62 production D1 submissions belong
to other collections. No existing candidate needs a move and no D1 row was changed.
D1 decision/draft/assessment/job responses can be truncated; they are not claimed
as exhaustive independent audits. Complete submissions and empty manifests are
the evidence for the absence of existing submitted Consensus candidates.

The old public /research/collections/consensus/ URL becomes a noindex redirect to
/research/bibliography/ with a usable HTML link. Console collection=consensus
links resolve to weekly. The empty legacy manifest is retained as a compatibility
receipt; workers no longer route new candidates there. Historical reports remain
historical. Source-level diagnostic usage counts remain provider provenance.

Consensus stays disabled pending the existing secure credential/free-plan checks.
No API usage, spending, scores, gates, decisions, cron cadence or site access policy
is changed. Hourly workers read the updated registry and routing implementation;
the paid classifier routes new work through weekly. Main's weekly discovery and
publication workflow dependencies remain unchanged.

Verification completed: 40 public collection tests; 122 pipeline, recovery,
date, review-release and publication tests; 67 discovery and review-worker tests;
90 console tests, TypeScript checking and the production console build. All eight
review manifests pass integrity validation. Pages staging validates 199 indexable
collection pages plus the retired redirect, SEO/schema/links and unchanged public
downloads. No accepted data files changed.

Published source commits: main c86796e and review branch 6ec24f3. The console
publishes through Sites with its owner-only audience preserved. This environment's
network policy denies the public ALEX domain and GitHub Actions API, so public
Pages deployment status and live HTTP/browser behavior remain unverified. Provider
traffic was mocked; no live Consensus call was made. The existing worker and
independent-monitor schedules are enabled and their latest recorded runs completed;
no post-change scheduled processing run is claimed as verified. Native scheduler
next_run_time remains null. Neither schedule requires Consensus-specific edits.

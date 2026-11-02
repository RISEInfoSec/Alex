# ALEX source expansion report — 2 November 2026

FIRST, M3AAWG and Bellingcat now use the existing Content Review Discovery inventory and weekly preflight. Consensus has a tested official-API adapter and remains disabled pending secure credentials and verified no-cost usage. This is a discovery/intake extension: publication of unsupported non-paper resource formats remains held.

## Measured initial historical pass

| Source | Unique source records | Repeated observations consolidated | Entered existing preflight | Intake rejected | Ready for editorial review | Published |
|---|---:|---:|---:|---:|---:|---:|
| FIRST | 886 | 3 | 84 | 0 | 0 | 0 |
| M3AAWG | 143 | 20 | 83 | 0 | 0 | 0 |
| Bellingcat | 284 | 21 | 13 | 6 | 0 | 0 |
| Consensus | 0 | 0 | 0 | 0 | 0 | 0 |
| Total | 1,313 | 44 | 180 | 6 | 0 | 0 |

Unique records include unresolved metadata-only URLs, editions and possible variants; they are not verified eligible publications. Consolidation refers to repeated source observations, not 44 removals from the public collection. No confirmed exact public-corpus duplicates or editorial-exclusion matches were found in this pass. Possible title/version/translation conflicts remain held for reconciliation. Six Bellingcat routine-news/promotional items were rejected at intake and retained in the audit inventory.

The initial temporary intake contained 250 held observations. Seventy sitemap-only entries were returned to the retained discovery inventory because their official title/author/content metadata is missing. Final preflight intake is 180. No existing human decision, reviewed hash or public record was changed. The remaining 1,127 unrejected identities remain outside preflight, including metadata-only URLs and deferred older material.

## Collections and coverage

FIRST: 16 index/library/guide/standard pages, annual publication metadata from 2016–2026, with recent material prioritized for preflight. Eighteen older annual indexes remain checkpointed. Contribution fragments distinguish items on annual pages. Standards/guides retain linked language, edition and format variants. Historical event downloads are restricted under FIRST's current notice; this run fetched public metadata, not those files. Restricted TLP content stays held.

M3AAWG: 16 index pages covering best practices from 2005 onward, supporting documents and policy comments. The visible update date is retained separately from stale Drupal creation dates. Translation/version relations and the conflicting 2026 Supply Chain listing/2025 file link remain unresolved holds. Original publishers/authors of third-party supporting documents require front-matter verification.

Bellingcat: six Resources/feed/sitemap pages, including methodology URLs from 2014–2026 and recent investigative case studies. Resource/tutorial labels are distinct from academic research; no peer-review claim is made. Sitemaps supply URL identities, not invented bibliographic metadata. Broader investigative archives beyond the recent general feed remain a coverage gap.

Consensus: zero historical searches performed. Official endpoint, response mapping, four focused queries and cost guards are implemented and tested. Original authors, institutions, journal, publisher, DOI, abstract, source URLs and citation counts are preserved where available; Consensus is intermediary attribution.

## Scheduling and failure handling

Use the existing hourly Content Review worker, Automation_0ff7fb9b800481919b48ddb2593b8f88, without changing its cadence or creating a second scheduler. Enabled FIRST/M3AAWG/Bellingcat sources refresh every seven days; unfinished enumeration and failures resume on subsequent hourly passes. Initial source runs succeeded independently; FIRST has remaining historical enumeration, M3AAWG and Bellingcat have no queued enumeration pages in this bounded pass. No claim of complete historical coverage is made.

Each source has its own successful/failed/not-due/disabled status, pending URLs, retrieval hashes, conditional headers and retry deadline. One origin's failure does not stop other sources. Requests are serial per origin, paced at least two seconds apart, with 20-second timeouts, robots checks and no login/challenge bypass.

The existing worker was found disabled after a recorded failed run with no diagnostic result. Restoring it and adding these source instructions is part of this rollout. An enabled schedule does not prove future unattended execution; the next recorded worker run remains the operational verification.

## Integration and safeguards

Configuration: config/discovery_sources.json and source registry. Adapters: tools/content_review/discover_sources.py. Durable inventory: existing content_review_archive_discovery_inventory.json. Intake and check state: existing weekly_review_manifest.json and content_review_preflight_status.json. Source checkpoints and receipts record actual measured stages.

All new preflight entries have unchecked format, access, metadata, duplicates, quality and schema gates. No keyword/title screen counts as substantive review. Fresh duplicate/exclusion comparisons use current main public corpus, current raw weekly intake, prepared collections and retained archive inventory. Updated metadata is preserved separately without rewriting approved content. Existing relevance scores, hard gates, slide/audio usefulness penalties, automatic acceptance rules and 1–20 manual admission are unchanged. No new source receives an approval or score bonus.

The current paid preflight and controlled publication executors require verified research_paper material. Standards, best-practice guides, technical reports and investigative journalism remain correctly typed and held wherever an existing resource-specific export path is missing. They are not mislabelled as papers to pass the executor. This is a remaining implementation limitation. A supported research paper can proceed through the existing checks and approval path; an authenticated Include still authorizes publication after all checks, without another approval or minimum batch.

## Tests and public verification

175 targeted pipeline, source and Content Review tests passed with zero failures/errors in run 41434639778. Tests cover parsing, attribution, TLP restrictions, update dates, translations, conflicting editions, news rejection, free-usage guards, entire-corpus DOI/title/URL matching, FIRST fragments, bounded intake, idempotency, unchanged decisions/hashes, source isolation, retry checkpoints, conditional refresh and single-writer lease refusal. The existing classification regression workflow also passed. The isolated QA/bootstrap workflow has no schedule; routine intake stays with the existing worker.

The live source pass succeeded, generated inventories were read back from GitHub, normalized intake was verified and console response size remained under its established limit. CI verified that public corpus files were not modified. No synthetic test item or unreviewed candidate was published.

Since zero new source records were published, public searchability of a new publication is not yet verified. Verify a real released candidate and its reviewed hash in deployed data/papers.json and public search after it completes the existing gates and approval route.

Evidence:
- config/content_review_source_discovery_intake_receipt.json
- config/content_review_source_discovery_validation.json
- config/content_review_source_discovery_state.json
- config/content_review_discovery_checkpoints/source-expansion-2026-11-02T11-08-00.965663+00-00.json
- https://github.com/RISEInfoSec/Alex/actions/runs/41434012838
- https://github.com/RISEInfoSec/Alex/actions/runs/41434639778

## Access, cost and remaining work

FIRST historical presentation access remains restricted; credentials or membership alone do not establish permission for public reuse. Consult the current official notice and obtain any required specific permission before retrieving/reusing files.

Consensus requires CONSENSUS_API_KEY in a supported private runtime secret binding and confirmed Free account status, with CONSENSUS_FREE_PLAN_CONFIRMED=true supplied privately, before enabling the config. No key was supplied, no live call made and no paid usage activated. Official current Free allowance is 30 shared API/MCP calls/month with no overage. The adapter limits itself to 24 attempted calls/month and checkpoints before each request. Paid plans may charge $0.05 per additional call; a local counter cannot prevent charges from a shared paid-account pool. Paid activation requires explicit authorization and account-wide cost controls. Subscription prices are separate.

Continue bounded mechanical checks and evidence enrichment for the 180 preflight records, acquire missing official metadata for retained URLs, reconcile versions, and extend existing material-specific export support where needed. Existing approvals retain publication priority over new intake.

Official access/API references:
- https://www.first.org/resources/presentation-access
- https://www.m3aawg.org/for-the-industry
- https://www.bellingcat.com/resources/
- https://help.consensus.app/en/articles/16516328-the-consensus-api
- https://docs.consensus.app/api-reference/search

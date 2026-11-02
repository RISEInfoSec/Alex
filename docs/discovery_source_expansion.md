# Discovery source expansion — 2 November 2026

Extends the existing hourly Content Review worker on codex/soups-corpus-review. No new scheduler, database, editorial queue, scoring rule or publication executor. The weekly academic pipeline on main is unchanged.

Read config/discovery_sources.json, source state, current main corpus/exclusions and existing workflow/material policies. Hold and verify the shared 30-minute SHA-guarded single-writer lease. Finish eligible publications first. Resume bounded source discovery alongside existing weekly/source preparation; prevent starvation. Seven-day incremental refresh; unfinished enumeration and transient failures resume on subsequent hourly passes.

Run:
    python -m tools.content_review.discover_sources --public-root /path/to/fresh-main --run-id THE_VERIFIED_LEASE_RUN_ID --write

Append observations to content_review_archive_discovery_inventory.json and at most 250 unresolved records per pass to the EXISTING weekly_review_manifest.json preflight records, with pending checks in content_review_preflight_status.json. All six gates start unchecked. Preserve prior records, decisions and reviewed hashes; source updates remain separate pending observations. Raw discovery is not review-ready. Existing qualifying automatic acceptance and immediate 1–20 manual admission remain unchanged. Source names confer no scoring bonus.

FIRST: Security Library; annual Papers & Presentations metadata; guides and standards. Prioritize 2022–2026, then bounded older archive metadata. Annual-page fragments identify distinct contributions. Standard languages, page sizes and editions remain grouped resource variants. Respect current presentation-access notice and TLP restrictions. This helper never downloads event files. Public guides/standards require their own material verification.

M3AAWG: best practices since 2005, supporting documents and public policy comments. Preserve visible update dates separately from stale outer Drupal creation dates. Reconcile translations and editions before public duplication. Supporting documents may originate elsewhere: verify authors/publisher from front matter. Known conflict: Cybercrime Supply Chain 2026 links to a 2025 PDF; a separate 2026 attachment is also listed. Hold that conflict.

Bellingcat: Resources, methodology feed, recent general feed and post sitemaps. Sitemap-only records have no invented title, author or abstract. Tutorials are OSINT methodology candidates; investigations require demonstrated transferable methods. Exclude routine news/promotions. These are investigative journalism, not automatically peer-reviewed papers. Broader investigation archives beyond the recent general feed remain a coverage gap.

Consensus: official GET https://api.consensus.app/v1/search using x-api-key. Preserve actual authors/institutions, journal, publisher, DOI, abstract, citations and original links. Consensus is intermediary provenance. Four focused queries; page one per query per weekly pass.

## Consensus authorization and costs

Disabled. No live Consensus call or paid usage is authorized. Supply CONSENSUS_API_KEY through a supported private runtime secret binding, verify the account is Free, supply CONSENSUS_FREE_PLAN_CONFIRMED=true privately, then enable the config. A key alone cannot activate requests. Never store the key in source, issues, logs, chat or public configuration.

Official current limits: Free 30 shared API/MCP calls/month with no additional usage; Pro/Team/Enterprise 500 included (maximum 1,000); Deep 2,000 included (maximum 10,000). Additional usage on eligible paid plans costs $0.05/call; subscriptions are separate. Reverify dashboard and terms at activation. The helper caps itself at 24 calls/month, records attempted calls durably BEFORE sending, makes no metered retries and uses no paid Threads/full-text-excerpt feature. Other clients share the allowance. A local counter cannot prevent paid-account overages: paid accounts require explicit authorization and account-wide cost controls. A supported secure runtime binding is still required.

## Existing executor limits

Current paid preflight and immutable publication executors require verified research_paper material. Guides, standards, technical reports and investigative journalism retain their correct types and remain held wherever a resource-specific schema/export path is missing. Never relabel them as research papers to force acceptance. Discovery is integrated; end-to-end publication of unsupported formats is not claimed. Continue supported research-paper checks and publication without another editorial vote.

## Reliability and validation

Serial requests per origin, two-second minimum spacing, 20-second timeouts, robots checks, conditional ETag/Last-Modified refresh, durable retry deadlines and isolated failure logs. Never bypass login, challenge or FIRST restrictions. DOI/canonical URL/normalized-title comparisons cover current public corpus, current raw weekly intake, prepared manifests and retained archive inventory. Possible versions are held. Unknown citations stay null.

Tests cover independent adapters, TLP, date reconciliation, editions/translations, news rejection, accurate journalism labels, Consensus attribution/no-charge guards, fragment identity, whole-corpus deduplication, bounded intake, idempotency, decision preservation, failure isolation, conditional refresh and leases. Run existing pipeline and Content Review tests too. The source-expansion Actions workflow is an isolated QA/bootstrap harness with NO schedule; routine discovery remains in the existing hourly worker. It never publishes synthetic or unreviewed material.

Live public search for a new source can be verified only after a real candidate passes six gates and the existing approval/publication path. Raw inventories and intake holds are not publications.

Official references:
- https://www.first.org/library/
- https://www.first.org/resources/presentation-access
- https://www.m3aawg.org/for-the-industry
- https://www.m3aawg.org/published-documents
- https://www.m3aawg.org/supporting-documents
- https://www.bellingcat.com/resources/
- https://help.consensus.app/en/articles/16516328-the-consensus-api
- https://docs.consensus.app/api-reference/search

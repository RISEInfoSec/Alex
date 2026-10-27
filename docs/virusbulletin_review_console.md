# Virus Bulletin in the ALEX Review Console

The user designated https://alex-research-review.neil-schwartzm917549.chatgpt.site/ as the review interface for these collections on 27 October 2026. Use the existing console from this point forward; do not deliver new standalone HTML review batches.

Collection ID: `virusbulletin`. Adapter: `normalized`. The console registry and prepared review manifest live on the existing `codex/soups-corpus-review` branch of RISEInfoSec/Alex. This collection registration does not merge or deploy ALEX and does not change its public corpus.

The first 40 candidates are prepared from substantive readings of official individual abstracts and, for VB-020, the original one-page poster. Batch 1 (VB-001–VB-020) was explicitly approved in conversation on 27 October 2026. Those approvals are carried forward with their existing candidate IDs and reviewed-content hashes. They are source-manifest decisions, not newly fabricated console submissions. Batch 2 (VB-021–VB-040) is pending, with twenty include recommendations: eighteen direct and two supporting (28 and 30).

Read submitted console decisions from production D1 before resuming ingestion. Only completed `review_submissions` and their corresponding `review_decisions` count; drafts do not. Preserve the source-manifest approvals for the first batch, together with their provenance, when reconciling with later console submissions. Later complete submissions supersede earlier decisions only against the same candidate content hash. Changed content requires review again.

All 40 were checked by title and URL, including close-title variants, against the retrieved 3,598-record public ALEX baseline; no matches were found. No exact title matches were found in the checked pending SOUPS queues. Refresh those checks before import. All 40 DOI and citation searches remain pending; a missing DOI is not a reason to exclude. No full research paper has been assessed. Material types and attribution uncertainties remain explicit.

Coverage: all 36 annual pages, 25 programme pages, 1,394 provisional programme entries plus four 2026 posters; forty items assessed and 1,358 discoveries unassessed. Programme tallies have not been independently reconciled. The first eleven years expose conference reports needing follow-up. Other ancillary sources remain incomplete.

Next: review batch 2 in the console, continue substantive screening of remaining 2026 contributions and then older years, and retain accepted/rejected decisions. Bibliographic reconciliation, source availability, quality scoring, taxonomy compatibility and controlled import remain separate work. No quality exceptions, public corpus writes, merges, deployment or schedules have been authorized by selection approval.

Exporter contract: numeric `review_batch` and `batch`, string `authors`, original `canonical_authors`, stable `candidate_id`, original `content_sha256`, explicit recommendation and evidence-based `review_reason`, official source URL and source notes. The presentation adapter does not recompute hashes merely because author arrays are displayed as semicolon-separated text.

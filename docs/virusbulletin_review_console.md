# Virus Bulletin in the ALEX Review Console

The user designated https://alex-research-review.neil-schwartzm917549.chatgpt.site/ as the review interface for these collections on 27 October 2026. Use the existing console from this point forward; do not deliver new standalone HTML review batches.

Collection ID: `virusbulletin`. Adapter: `normalized`. The console registry and prepared review manifest live on the existing `codex/soups-corpus-review` branch of RISEInfoSec/Alex. This collection registration does not merge or deploy ALEX and does not change its public corpus.

The first 60 candidates are prepared from substantive readings of official individual abstracts and, for VB-020, the original one-page poster. Batch 1 (VB-001–VB-020) was explicitly approved in conversation on 27 October 2026; those source-manifest approvals retain their original hashes and provenance. Batch 2 (VB-021–VB-040) was submitted through the console on 27 October 2026: 20 approved, none rejected, revision 1. All 20 saved decision rows matched the reviewed candidate IDs and content hashes before reconciliation. There are now 40 accepted selections and no rejections.

Batch 3 (VB-041–VB-060) is pending: eighteen include recommendations and two discuss recommendations (47, Landlock telemetry; 53, the IoB panel). Material types distinguish ordinary talks, TIPS talks, the workshop, partner presentation, panel and reserve contribution. Four transient source retrieval failures succeeded on one retry each. No full paper or tool was assessed in this batch.

Read submitted console decisions from production D1 before resuming ingestion. Only completed `review_submissions` and their corresponding `review_decisions` count; drafts do not. Preserve the source-manifest approvals for the first batch, together with their provenance, when reconciling with later console submissions. Later complete submissions supersede earlier decisions only against the same candidate content hash. Changed content requires review again.

All 60 were checked by title and URL, including close-title variants, against the retrieved 3,598-record public ALEX baseline; no matches were found. No exact title matches were found in the checked pending SOUPS queues. Refresh those checks before import. All 60 DOI and citation searches remain pending; a missing DOI is not a reason to exclude. No full research paper has been assessed. Material types and attribution uncertainties remain explicit.

Coverage: all 36 annual pages, 25 programme pages, 1,394 provisional programme entries plus four 2026 posters; sixty items assessed and 1,338 discoveries unassessed. Programme tallies have not been independently reconciled. The first eleven years expose conference reports needing follow-up. Other ancillary sources remain incomplete. Fifteen provisional 2026 entries remain unassessed; earlier-year substantive screening is still outstanding.

Next: review batch 3 in the console, continue substantive screening of remaining 2026 contributions and then older years, and retain accepted/rejected decisions. Bibliographic reconciliation, source availability, quality scoring, taxonomy compatibility and controlled import remain separate work. No quality exceptions, public corpus writes, merges, deployment or schedules have been authorized by selection approval.

Exporter contract: numeric `review_batch` and `batch`, string `authors`, original `canonical_authors`, stable `candidate_id`, original `content_sha256`, explicit recommendation and evidence-based `review_reason`, official source URL and source notes. The presentation adapter does not recompute hashes merely because author arrays are displayed as semicolon-separated text.

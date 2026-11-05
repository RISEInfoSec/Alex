# Manual text-resource route

Owner approval: 4 November 2026, America/Toronto. Contract: `manual-text-resources-v1` in `config/content_review_resource_policy.json`. This is workflow authorization, not a human acceptance decision for a candidate.

Supported types are best-practice guides, technical reports and investigative journalism. Keep actual types. Slides, recordings, posters and transcripts remain outside this extension. Existing paper thresholds, exclusions, access controls and provider rules remain unchanged. No numeric citation surrogate, automatic acceptance or paper relabelling is permitted.

## Preparation

Use the existing source runner only when permitted material is missing. Reuse verified retained full text and the source/text digests. Keep accountability, original publication information, edition/version and modification dates distinct. A month-only publication date is never invented as a day or used as verified day-precision membership in New publications.

After current format/access/duplicate clearance, assess the retained content. Record each criterion, evidence and limitations: accountability, substantive material, investigative relevance, and supported evidence or actionable guidance; guides additionally require a version and actionable scope, reports methods and data provenance, and investigations sourcing and a demonstrated investigative method. Identify uncertain claims and any uninspected linked media. A news mention alone does not pass.

Use `tools/content_review/prepare_resource.prepare` with the explicit assessment, editorial synopsis and closed-taxonomy classification with rationale. This is a source assessment by the worker, not a paid-paper classification or a human decision. The validated classification contract uses existing enums; no fallback Other is fabricated. The actual resource type, qualitative assessment digest and explicit synopsis label survive the real publisher's disposable serialization test. Keep the full earlier reviewed record in version history. Bind the recommendation and admit immediately to a new sealed batch of 1–20, preserving current submissions and decisions. Never rerun completed source checks merely to fill a budget.

## Human decision and release

The console displays type, synopsis, qualitative evidence and limitations. Its decision context includes the assessment digest. Refresh the complete D1 submission snapshot and reconcile the latest decision/revision. Use `alex.resource_types.release_record(row, decision, submission)` only on a current completed human approval. It rejects absent or stale assessment snapshots. Use the existing `approved-*.json` release request path and `scripts/release_discovery_backlog.py`; the older paper-only release path remains paper-only.

The release executor checks all six gates, closed taxonomy, content hash, assessment digest, completed human submission, exact target serialization, current exclusions/duplicates and the assessed source. Exact PDF bytes or exact HTML bytes must still match. Dynamic HTML changes are a version-reconciliation hold, never permission to substitute an unassessed source. When a change is purely presentational, retain both byte versions and re-evaluate/rebind only with documented evidence; never remove the content-bound human check. Public output retains the type and qualitative limitations, with no paper quality tier or seminal claim.

## Demonstrated candidates

On 5 November UTC (4 November Montréal), two retained-source candidates completed preparation with zero source, paid or OpenAlex requests: M3AAWG #178 in batch 34 (guide, recommendation Discuss) and Bellingcat #209 in batch 27 (investigation, recommendation Include). Both await a human decision. They were not published. Technical-report handling has regression coverage but no real report was processed in this maintenance demonstration.

The M3AAWG guide was assessed as supporting incident-response communications, with limited direct evidence-collection value. The Bellingcat investigation was assessed for transferable geolocation and corroboration methods; linked primary media and every incident claim were not independently reproduced.

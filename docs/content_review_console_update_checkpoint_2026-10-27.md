# Content Review console update checkpoint — 27 October 2026

Status: implemented and checked locally, NOT pushed or deployed. The execution environment disconnected before the packaging call could begin. Production remains Site version 1.

Site: appgprj_6ae0e13117b48191b3b024311ee18342. Preserve owner-private access. Local checkout: sites/alex-review under the rise infosec project. Source helper opened hosted source at commit af0485aaac252ff28c38f3d7b65fc83625abddf7 before edits. Never deploy the old source as if it contained these changes.

Local changes to recover when the workspace reconnects:
- app/review.tsx: Pending/Archive views, compact batch selector, refresh and successful submission select pending work, completed decisions remain archived, accepted/rejected archive filters, visible source freshness and submission pause on fallback.
- lib/review-core.mjs: batchSummaries, selectBatch, reviewFeedback, recommendationContext, materialSummary. Presentation abstracts, slides, posters, transcripts, recordings and research papers distinguished; PDF extension never establishes paper status. Cards state assessment depth.
- lib/review-source.mjs: raw GitHub source cache busting and explicit failures.
- lib/review.ts: recommendation hashes, safe source-failure logging, current hash-matched decision overlay and calibration summary.
- db/schema.ts and generated drizzle/0002_majestic_famine.sql (+ snapshot and journal): nullable recommendation_snapshot TEXT on review_decisions. Historical migrations remain unchanged.
- lib/review-sql.mjs and app/api/decisions/route.ts: atomically store recommendation/relevance/reason/material-kind snapshot with each immutable decision; validate displayed recommendation hash; preserve revision and idempotency safeguards.
- tests: queue-selection regression, partial/content-changed batches, frozen versus historical feedback, source cache bypass, stale recommendations, material types, snapshot persistence; existing storage protection tests retained.
- app/globals.css: compact navigation, feedback panel and material-context note.
- README update was attempted in the failed packaging cell and did not complete; update it when resuming.

Validation completed: TypeScript noEmit passed; all 16 Node tests passed; full five-stage Vinext build passed with official Node v22.23.4 downloaded from nodejs.org and verified against its official SHA-256 checksum. App-bundled Node could not load the native build dependency because of Team-ID validation; no protection was disabled. Official standalone Node built successfully.
Local browser preview and local D1 migration application were blocked by listen EPERM on 127.0.0.1. The migration has NOT been applied to production. Recheck its actual status before publishing; Sites applies hosted migrations during deployment. Package/build the current exact source, push with the Sites source helper, then publish owner-private and verify the authenticated UI. Browser QA of the changed UI is outstanding.

Observed user state:
- SOUPS batch 9 was submitted 2026-10-27T22:05:05.929Z: 13 accepted, 7 rejected, revision 1. Fetch the exact receipt from production D1.
- Virus Bulletin batch 4 was submitted 2026-10-27T22:03:10.999Z: 18 accepted, 2 rejected, revision 1. Fetch exact ID and decision rows from production D1.
- The authenticated Safari console showed all 178 SOUPS numbered records complete (162 accepted, 16 rejected). Both newest prepared batches have been exhausted; do not report the forty as still pending.
- Refresh previously retained a completed selected batch; the source was not necessarily missing. Fix navigation and replenish actual pending material.
- No fresh replacement batch or 250-item buffer was prepared during this console update. Reconcile decisions first, then resume substantive screening. Do not count raw discoveries or automatically accepted entries as manual-review buffer.

Policy now saved remotely:
- config/content_review_material_policy.json: user-confirmed major resource-usefulness deduction for decks/presentations without verified substantive audio; no automatic acceptance; a matching full recording with usable audio removes that deduction after verification. YouTube embed alone is insufficient. Presentations remain distinct from papers. Numeric amount not calibrated, live scoring integration pending.
- config/content_review_workflow.json version 4 links this rule. Existing research-paper scoring and qualifying automatic route remain unchanged.
- Review decisions do not currently update score weights or train a model. New console snapshots and aggregate feedback provide calibration evidence; historical comparisons must be labelled as comparisons against current recommendations.

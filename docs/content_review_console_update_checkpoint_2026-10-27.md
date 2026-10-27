# Content Review console checkpoint — 27 October 2026

The console update is deployed successfully as Site version 2. Project appgprj_6ae0e13117b48191b3b024311ee18342; source commit b0c1d8fb234ecb3fac68838071abd7d554b0e87f; deployment appgdep_6ae1240563888191858b5cf83f8bbd6d. Owner-private access preserved. The nullable recommendation_snapshot production column was verified after migration.

Features: Pending/Archive separation; compact batch selectors; refresh selects pending work; raw-source cache bypass; visible source failures; immutable recommendation snapshots and historical-calibration summary; distinct paper/presentation/poster/recording types and assessment depth; source-independent major presentation-usefulness deduction when substantive audio is absent or unverified. A matching full recording must be verified; an embed alone is insufficient. Numeric research-paper weights remain unchanged, and automatic score learning is not implemented.

Validation: TypeScript passed, 19 console tests passed, full production build passed. Authenticated Safari verified the new Pending and Archive views, retained SOUPS decisions, and SOUPS batch 10 with 20 to review. No test decisions were submitted in production.

New source manifests:
- SOUPS batch 10: 179–198, twenty fresh research-paper candidates (seventeen Include, three Exclude). Official individual abstracts and citation metadata were freshly checked; full papers not assessed. Earlier batch 9 was reconciled from completed D1 decisions: 13 accepted, seven rejected. Current SOUPS source counts: 162 accepted, 16 rejected, 20 pending.
- Virus Bulletin batch 5: 81–92, twelve new written conference papers. Each linked PDF was confirmed as prose paper material, and abstracts/opening material inspected. No complete-paper review is claimed. The primary paper's title/author differences from its presentation are retained in notes. Batch 4 was reconciled from completed D1 decisions: 18 accepted, two rejected. Current Virus Bulletin counts: 77 accepted, three rejected, twelve pending.
- Eight presentation-only discoveries were held outside the ready buffer pending suitable paper or recording evidence. See config/virusbulletin_presentation_context_holds.json.
- Do not append more records to an already submitted batch 5. Next Virus Bulletin batch begins at review number 101 (batch 6); unused numbers 93–100 are deliberately left unused to preserve stable batch membership.

Prepared global manual-review buffer added here: 32 candidates, not 250. The confirmed strictly-below-100 → refill-to-250 rule is still awaiting the genuine background-worker/outbox integration. No replacement polling schedule was created. Mechanical assessment auto-dispatch remains pending that integration.

Relevant policy: config/content_review_material_policy.json applies to every source. The reusable categorical assessment is in tools/content_review/resource_usefulness.mjs. Existing automatic acceptance for qualifying regular research papers remains intact. Editorial decisions do not authorize curated import, merge or public ALEX deployment.

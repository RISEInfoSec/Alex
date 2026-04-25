# Alex Architecture (current state)

This is the **operational** view of how the pipeline runs today. For the original v2.1 spec / requirements, see [`alex_architecture_v2_1.md`](alex_architecture_v2_1.md). For setup and runbook, see the [README](../README.md).

## Pipeline stages

| # | Stage           | CLI                       | Reads                          | Writes                                                                                  | Notes |
|---|-----------------|---------------------------|--------------------------------|-----------------------------------------------------------------------------------------|-------|
| 1 | Discover        | `alex.cli discover`       | `config/*.json`                | `data/discovery_candidates.csv`                                                         | Fans out across sources concurrently; pagination within each source stays serial. |
| 2 | Citation chain  | `alex.cli chain`          | `discovery_candidates.csv`     | `discovery_candidates.csv` (augmented)                                                  | Forward (OpenAlex `cited_by_api_url`) + backward (Semantic Scholar references). |
| 3 | Quality gate    | `alex.cli score`          | `discovery_candidates.csv`     | `quality_metrics.csv`, `accepted_candidates.csv`, `review_queue.csv`, `rejected_candidates.csv` | Peer-reviewed: auto-include ≥60, review 45–59.99, reject <45. Preprints (arXiv): auto-include ≥35, review 20–34.99, reject <20. Thresholds in `config/quality_weights.json`. |
| 4 | Harvest         | `alex.cli harvest`        | `accepted_candidates.csv`      | `accepted_harvested.csv`                                                                | Parallelised across candidates; Crossref → OpenAlex → Semantic Scholar fallback. |
| 5 | Rescore         | `alex.cli rescore`        | `accepted_harvested.csv`       | `accepted_harvested.csv` (filtered), `rescore_metrics.csv`                              | Re-runs relevance with full abstracts; preprint-aware thresholds. |
| 6 | Classify (LLM)  | `alex.cli classify`       | `accepted_harvested.csv`       | `accepted_classified.csv`                                                               | OpenAI `gpt-4o-mini` via `/v1/responses`. Aborts on `insufficient_quota`. Tracks token usage. |
| 7 | Publish         | `alex.cli publish`        | `accepted_classified.csv`      | `data/papers.json`, `data/osint_cyber_papers.csv`                                       | Additive merge on DOI/title; never overwrites existing rows on empty input. |

After Publish, the `pipeline.yml` `deploy` job stages `index.html`, `papers.json`, and `osint_cyber_papers.csv` to the `_site/` artifact and pushes it to GitHub Pages.

## Data ownership

- `data/discovery_candidates.csv` — raw candidates (mutable; grows each Discover/Chain run)
- `data/accepted_candidates.csv` / `data/review_queue.csv` / `data/rejected_candidates.csv` — Quality gate buckets
- `data/accepted_harvested.csv` — accepted set with full bibliographic metadata
- `data/rescore_metrics.csv` — audit trail for which papers were reconsidered in the post-harvest rescore window
- `data/accepted_classified.csv` — internal corpus with LLM tags. **Additive across runs** — papers persist even if a future quality run wouldn't accept them.
- `data/papers.json` / `data/osint_cyber_papers.csv` — public corpus served via Pages

## Concurrency rules

- **Across upstream sources**: parallel is fine (each has its own rate-limit budget).
- **Within a single free academic source**: pagination stays **serial** to honor the polite-API contract (`time.sleep(0.5)` in `HttpClient.get_json`).
- **Paid commercial APIs (OpenAI)**: rate limits are the contract — concurrency within published RPM/TPM is fine if needed; the current classify loop is serial because steady-state load is small.

## Failure semantics

- **Network blips / 429 rate-limit / 5xx** during classify → log warning, fall back to default tags for that paper, continue.
- **Account-level OpenAI errors** (`insufficient_quota`, `billing_hard_limit_reached`, `account_deactivated`, `invalid_api_key`, 401, 403) → **raise `OpenAIQuotaError` and abort the run**. This is intentional — silent fallback corrupted 1,499 papers as `Category="Other"` on 2026-04-25 before the loud-failure patch.
- **Empty input to a stage** → write empty placeholder where downstream `git add` requires the file, but do not overwrite an existing populated output.

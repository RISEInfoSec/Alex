# Retrieval, Gating & Classification — reference

Authoritative reference for *how* candidates are found, scored, chained, and tagged. Pairs with [`architecture.md`](architecture.md) (per-stage I/O view). Code links point at the canonical home for each rule so this doc doesn't silently drift from runtime behaviour.

---

## 1. Discovery — query families & enabled sources

### Query families
The 16 fixed query phrases are stored in [`config/query_registry.json`](../config/query_registry.json):

```
open source intelligence            OSINT methodology
OSINT investigation                 social media intelligence
digital investigation techniques    threat intelligence collection
internet investigation methods      dark web intelligence
OSINT research                      open source investigation
cybersecurity                       cybercrime research
cybercrime                          online threats
APT                                 advanced persistent threats
```

Each query is fanned out concurrently to every enabled connector; pagination *within* a connector stays serial under `HttpClient`'s polite delay (`time.sleep(0.5)`). See [`alex/pipelines/discovery.py`](../alex/pipelines/discovery.py).

### Connector gate
Whether each upstream connector actually fires is controlled by `connectors.<name>.enabled` in [`config/query_registry.json`](../config/query_registry.json):

| Connector            | Default | Notes |
|----------------------|---------|-------|
| `openalex`           | enabled  | Primary source for both discovery and forward citation chaining. |
| `crossref`           | enabled  | DOI-based discovery and metadata fallback. |
| `arxiv`              | enabled  | RSS feed (preprint source — papers from here route through the preprint scoring ladder). |
| `zenodo`             | enabled  | Repository discovery. |
| `github`             | enabled  | Code/whitepaper repository discovery. |
| `semantic_scholar`   | disabled | Requires `SEMANTIC_SCHOLAR_API_KEY`; gates both discovery and S2 citation backward chaining. |
| `core`               | disabled | Has a 5xx circuit-breaker (`circuit_break_5xx: 3`). |

Sources that aren't true API connectors (Google Scholar, Dimensions, BASE, IEEE, ACM, USENIX, RAND, CSIS, Atlantic Council, etc.) are listed in [`config/source_registry.json`](../config/source_registry.json) and routed to the **manual-assist** workflow rather than auto-discovered. See [`config/manual_assist_sources.json`](../config/manual_assist_sources.json).

### arXiv categories
Filtered to the cyber/AI-relevant categories in [`config/arxiv_categories.json`](../config/arxiv_categories.json):

```
cs.CR (cryptography & security)   cs.AI (AI/ML)
cs.CY (computers & society)       cs.SI (social/information networks)
cs.IR (information retrieval)     cs.NI (networking)
```

---

## 2. Citation chaining

Implemented in [`alex/pipelines/citation_chain.py`](../alex/pipelines/citation_chain.py).

### Algorithm
1. Sort `data/discovery_candidates.csv` by `citation_count` desc, take **top 100** (`CITATION_CHAIN_TOP_N`). Higher-cited seeds yield richer chains; everything else is exponentially diminishing returns.
2. For each seed (parallel across 8 workers):
   - **Forward chain (OpenAlex):** title-search OpenAlex → up to 3 hits (`oa_search_limit`) → for each, fetch `cited_by_api_url` → take up to 5 citing works (`oa_cited_by_limit`).
   - **Backward chain (Semantic Scholar, gated):** S2 title-search → up to 3 hits (`ss_search_limit`) → for each, fetch up to 5 references (`ss_refs_limit`). Skipped entirely if S2 isn't enabled or `SEMANTIC_SCHOLAR_API_KEY` is unset (avoids a flood of 429s).
3. Dedup new candidates by `normalize_title` against the existing corpus and within the batch (first occurrence wins).

### Output shape
Each new row is appended to `data/discovery_candidates.csv` with:

| Column | Forward (OpenAlex) | Backward (S2) |
|---|---|---|
| `discovery_source` | `OpenAlex citation chain` | `Semantic Scholar citation chain` |
| `inclusion_path` | `forward chaining` | `backward chaining` |
| `discovery_query` | seed candidate's title | seed candidate's title |

### Tuning
The four limits and worker count are settable via `connectors.openalex.citation_chain_*` and `connectors.semantic_scholar.citation_chain_*` in `query_registry.json` so politeness/depth can be tuned without a code change. Defaults at top of `citation_chain.py`.

### Spec gap
The v2.1 spec also lists **author chaining** (other works by the same authors). Not implemented — the discovery pool from forward+backward chaining has been sufficient so far. Tracked under `docs/alex_architecture_v2_1.md` § Citation chaining.

---

## 3. Quality gate

Implemented in [`alex/pipelines/quality_gate.py`](../alex/pipelines/quality_gate.py); scoring helpers in [`alex/utils/scoring.py`](../alex/utils/scoring.py).

### Score components
Each candidate gets four signals normalised to `[0, 1]`:

| Signal | Formula |
|---|---|
| `venue_score`       | `1.0` if any term in [`config/venue_whitelist.json`](../config/venue_whitelist.json) appears in the venue (case-insensitive); `0.4` for any other non-empty venue; `0.2` if blank. |
| `citation_score`    | `min(1.0, log1p(citations / age) / log1p(100))` where `age = max(1, current_year - year + 1)`. NaN/missing citations → `0.0`. |
| `institution_score` | `0.8` if affiliations contain any of `university`, `institute`, `laboratory`, `nato`, `rand`, `oxford`, `cambridge`, `mit`, `stanford`; `0.4` for any other non-empty text; `0.2` if blank. |
| `relevance_score`   | Tokenises the 16 query phrases (≥3-char tokens, stopwords removed) and counts substring hits in `title + abstract`. Scaled so ~⅓ keyword coverage saturates to `1.0`. |

### Total quality score
Weighted sum + institution bonus, from [`config/quality_weights.json`](../config/quality_weights.json):

```
total = (venue_score      * 0.35
       + citation_score   * 0.40
       + relevance_score  * 0.25) * 100
       + (10.0 if institution_score >= 0.7 else 0.0)
```

### Routing thresholds
| Tier              | Peer-reviewed (default) | Preprint (arXiv etc.) |
|-------------------|-------------------------|------------------------|
| **Auto-include** | total ≥ **60.0**        | total ≥ **35.0**       |
| **Review queue** | 45.0 – 59.99            | 20.0 – 34.99           |
| **Reject**       | < 45.0                  | < 20.0                 |

Source: [`config/quality_weights.json`](../config/quality_weights.json) (`auto_include_threshold`, `review_threshold`, `preprint_auto_include_threshold`, `preprint_review_threshold`).

> **Note:** `config/quality_thresholds.json` exists with older 75/45 numbers — it is **not** read by the quality gate; `quality_weights.json` is. The thresholds doc is left in place for spec history; the weights file is the live runtime config.

### Preprint detection
A row is a preprint iff `discovery_source ∈ {"arXiv", "arXiv RSS"}` (see `is_preprint` in `alex/utils/scoring.py`). The legacy `arXiv RSS` label is kept for back-compat with rows from the prior connector implementation. Preprints are routed on the lower threshold ladder because they structurally lack venue/citation/institution signal — penalising them against the peer-reviewed thresholds would reject relevance-heavy work that hasn't been indexed yet.

---

## 4. Post-harvest rescore

Implemented in [`alex/pipelines/rescore.py`](../alex/pipelines/rescore.py).

Discovery-time abstracts are sparse, so the initial Quality gate sees incomplete text. After Harvest enriches abstracts from Crossref/OpenAlex/S2, **Rescore** re-runs `relevance_score` against the now-enriched text, recomputes the total, and re-applies the auto-include threshold.

- Reads `accepted_harvested.csv`, writes the filtered set back plus an audit `rescore_metrics.csv`.
- Uses the same scoring helpers and the **same threshold ladder** as the Quality gate (peer-reviewed 60 / preprint 35).
- Emits an empty `rescore_metrics.csv` even on empty input so downstream `git add` doesn't fail.
- A `rescore_run_id` token is written to `.rescore_window.json` so `Classify` knows which existing classified rows to prune (the additive corpus model — papers reconsidered in the current window are removed and re-added based on the rescored verdict).

---

## 5. Classification (LLM)

Implemented in [`alex/pipelines/classify.py`](../alex/pipelines/classify.py).

### Model
`gpt-4o-mini` via OpenAI's `/v1/responses` endpoint by default. Override with the `OPENAI_MODEL` repo variable.

### Prompt taxonomy
The prompt instructs the model to return JSON only, with these fields:

| Field | Cardinality | Allowed values (from prompt) |
|-------|-------------|-------------------------------|
| `Category`           | one of | Digital Forensics, Threat Intelligence, OSINT Methodology, Network Security, Privacy & Surveillance, Cybercrime, **Other** |
| `Investigation_Type` | one of | Network Investigation, Social Media Analysis, Dark Web Analysis, Malware Analysis, Attribution, **Other** |
| `OSINT_Source_Types` | list   | Social Media, Public Records, Dark Web, DNS/WHOIS, Satellite Imagery, Government Data, … |
| `Keywords`           | list   | model-generated key terms |
| `Tags`               | list   | model-generated misc labels |
| `Quality_Tier`       | one of | Seminal, High, **Standard**, Exploratory |

The "e.g." in the prompt means the model may emit values outside the listed options for `Category`, `Investigation_Type`, `OSINT_Source_Types`. The downstream site treats them as free-form strings — only `Other` and `Standard` have specific behaviour (the fallback values).

### Seminal flag
Set independently of the LLM: `Seminal_Flag = "TRUE"` iff `citation_count >= 500`, else `"FALSE"`. Source: `_safe_citation_count(row)` in `classify.py`. The threshold lives in [`config/quality_thresholds.json`](../config/quality_thresholds.json) as `seminal_citation_threshold` but the runtime value is hard-coded in `classify.py` line 146.

### Failure semantics
- **Transient errors** (network blip, 429 rate limit not tagged as quota, 5xx, malformed JSON): log warning, fall back to `FALLBACK` constants (`Category="Other"`, `Quality_Tier="Standard"`, etc.), continue.
- **Account-level errors** (`insufficient_quota`, `billing_hard_limit_reached`, `account_deactivated`, `invalid_api_key`, HTTP 401, HTTP 403): raise `OpenAIQuotaError` and abort the entire run. Silent fallback on these once corrupted 1,499 papers as `Category="Other"` (2026-04-25), so loud failure is now mandatory.

### Token-usage instrumentation
Each run resets `_TOKEN_USAGE` and prints a summary at the end:

```
OpenAI usage: <calls> calls, <input> input + <output> output = <total> total tokens
```

Token totals are scraped from each successful response's `usage` block, so failed/fallback calls don't contribute. Pricing for `gpt-4o-mini` is bring-your-own — the doc-of-record is OpenAI's pricing page.

---

## 6. Additive corpus contract

`data/accepted_classified.csv` is **append-only across runs**, with the rescore window as the only mechanism that removes rows:

- New rows from the current run are merged in (DOI-or-normalised-title dedup key).
- Rows whose key appears in `data/rescore_metrics.csv` for the current `rescore_run_id` are removed before the merge — this is how a paper that was previously accepted but now scores below threshold disappears.
- Empty input never wipes the corpus; `publish.py` writes empty placeholder CSV/JSON only if those files don't already exist.

This contract is what makes the Monday cron safe to re-run: it can only add or replace, never silently truncate.

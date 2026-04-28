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

### Vetoes (run before the threshold cascade)

Two hard rejections evaluated *before* `total_quality_score` is compared to thresholds. They catch papers that score high on prestige (venue + citations) but have no actual topic overlap with the OSINT/cyber registry — the dominant noise mode caught in the 2026-04-27 cleanup (cardiology guidelines, capital-structure economics, biology toolkits, etc. arriving via forward citation chaining).

| Veto | Rejection reason |
|---|---|
| **Anchor term** — title + abstract must contain at least one term from `config/query_registry.json::core_keywords` (cyber, osint, malware, phishing, dark web, threat intelligence, …). | `No core cyber/OSINT term` |
| **Relevance floor** — `relevance_score >= relevance_floor` (default `1.0`, i.e. *some* registry-keyword overlap required). | `Below relevance floor` |

A paper failing either veto is rejected outright regardless of `total_quality_score`. Both vetoes apply to peer-reviewed papers and preprints alike. The same vetoes also run in **Rescore** (section 4) so post-harvest demotions stay consistent.

Source: `core_keywords` in `config/query_registry.json` and `relevance_floor` in `config/quality_weights.json`.

### Routing thresholds
Applied only to candidates that survive both vetoes.

| Tier              | Peer-reviewed (default) | Preprint (arXiv etc.) |
|-------------------|-------------------------|------------------------|
| **Auto-include** | total ≥ **60.0**        | total ≥ **35.0**       |
| **Review queue** | 45.0 – 59.99            | 20.0 – 34.99           |
| **Reject**       | < 45.0                  | < 20.0                 |

Source: [`config/quality_weights.json`](../config/quality_weights.json) (`auto_include_threshold`, `review_threshold`, `preprint_auto_include_threshold`, `preprint_review_threshold`).

### Preprint detection
A row is a preprint iff `discovery_source ∈ {"arXiv", "arXiv RSS"}` (see `is_preprint` in `alex/utils/scoring.py`). The legacy `arXiv RSS` label is kept for back-compat with rows from the prior connector implementation. Preprints are routed on the lower threshold ladder because they structurally lack venue/citation/institution signal — penalising them against the peer-reviewed thresholds would reject relevance-heavy work that hasn't been indexed yet.

---

## 4. Post-harvest rescore

Implemented in [`alex/pipelines/rescore.py`](../alex/pipelines/rescore.py).

Discovery-time abstracts are sparse, so the initial Quality gate sees incomplete text. After Harvest enriches abstracts from Crossref/OpenAlex/S2, **Rescore** re-runs `relevance_score` against the now-enriched text, recomputes the total, and re-applies the auto-include threshold.

- Reads `accepted_harvested.csv`, writes the filtered set back plus an audit `rescore_metrics.csv`.
- Uses the same scoring helpers and the **same threshold ladder** as the Quality gate (peer-reviewed 60 / preprint 35).
- Applies the **same anchor-term and relevance-floor vetoes** as the Quality gate (section 3) so post-harvest demotions stay consistent.
- **Drops papers with empty abstract.** A paper that survived harvest without an abstract has nothing useful for classify (LLM defaults to `Other` on title alone) or for a corpus reader (no summary on the site). Filter at rescore so we don't burn OpenAI tokens on guaranteed-`Other` classifications. Source: `_passes` in `rescore.py`.
- Emits an empty `rescore_metrics.csv` even on empty input so downstream `git add` doesn't fail.
- A `rescore_run_id` token is written to `.rescore_window.json` so `Classify` knows which existing classified rows to prune (the additive corpus model — papers reconsidered in the current window are removed and re-added based on the rescored verdict).
- Standalone workflow: [`.github/workflows/rescore.yml`](../.github/workflows/rescore.yml) (`workflow_dispatch` only). The same step also runs as part of the full Pipeline.

---

## 5. Classification (LLM)

Implemented in [`alex/pipelines/classify.py`](../alex/pipelines/classify.py).

### Model
`gpt-4o-mini` via OpenAI's `/v1/responses` endpoint by default. Override with the `OPENAI_MODEL` repo variable.

### Output schema (strict-mode structured outputs)
The request body sends `text.format = {"type": "json_schema", "name": "PaperClassification", "schema": CLASSIFICATION_SCHEMA, "strict": True}`. With `strict=True` the model is *required* to return a JSON object that matches the schema exactly — values for `Category`, `Investigation_Type`, and `OSINT_Source_Types` must come from the listed enums or the request fails server-side. Source: `CLASSIFICATION_SCHEMA` in `classify.py`.

| Field | Cardinality | Allowed values |
|-------|-------------|----------------|
| `Category` | one of | OSINT Methodology, Social Media & SOCMINT, Dark Web & Underground, Cyber Threat Intelligence, Digital Forensics & Evidence, Malware & Exploits, Vulnerability Research, Disinformation & Influence, Cybercrime & Fraud, Network & Infrastructure Security, IoT & CPS Security, Privacy & Surveillance, AI/ML for Security, Foundations & Surveys, **Other** |
| `Investigation_Type` | one of | Network Investigation, Social Media Analysis, Dark Web Analysis, Malware Analysis, Attribution, Phishing Analysis, Forensic Investigation, Threat Hunting, Vulnerability Assessment, Incident Response, **Other** |
| `OSINT_Source_Types` | list of | Social Media, Public Records, Dark Web, DNS/WHOIS, Satellite Imagery, Government Data, News Media, Forums & Communities, Code Repositories, Corporate Records, Court Records, Academic Literature, Leaked Data, Other |
| `Keywords` | list   | model-generated key terms (free-form) |
| `Tags`     | list   | model-generated misc labels (free-form) |

When the enum doesn't reasonably fit a paper, the model selects `Other`. A run with `Other` rate above ~20% on `Category` is a signal to add a category, not to drift the enum on the model's whim — every change to the enum lists is a deliberate schema change.

### Quality_Tier — derived, not LLM-set
Through 2026-04-28, `Quality_Tier` was an LLM-set field that the model filled with `"Standard"` ~99% of the time because the prompt offered no criteria. Now derived deterministically in [`alex/pipelines/publish.py`](../alex/pipelines/publish.py)::`_quality_tier` from `total_quality_score`:

| Tier | Threshold |
|---|---|
| `High` | total_quality_score ≥ 75 |
| `Standard` | 60 ≤ score < 75 |
| `Exploratory` | < 60 |

The field is no longer in the classify schema or in `accepted_classified.csv`; it is computed at publish time and only appears in `data/papers.json`.

### Seminal flag
Set independently of the LLM: `Seminal_Flag = "TRUE"` iff `citation_count >= seminal_citation_threshold` (default `500`), else `"FALSE"`. Source: `_safe_citation_count(row)` and `_seminal_threshold()` in `classify.py`; threshold lives in [`config/quality_weights.json`](../config/quality_weights.json) as `seminal_citation_threshold`.

### Response parsing
The OpenAI Responses API returns the model's text under `data["output"][i]["content"][j]["text"]`. The top-level `output_text` convenience field was reliable through Apr 25 then started returning empty in our request shape on Apr 27 (100% empty across 519 calls — the corpus that day was 100% fallback `Other` until the parser was fixed). `_extract_response_text` prefers `output_text` when populated and falls back to walking the structured array.

### Failure semantics
- **Transient errors** (network blip, 429 rate limit not tagged as quota, 5xx, malformed JSON): log warning, fall back to `FALLBACK` constants (`Category="Other"`, `Investigation_Type="Other"`, empty arrays for the rest), continue.
- **Account-level errors** (`insufficient_quota`, `billing_hard_limit_reached`, `account_deactivated`, `invalid_api_key`, HTTP 401, HTTP 403): raise `OpenAIQuotaError` and abort the entire run. Silent fallback on these once corrupted 1,499 papers as `Category="Other"` (2026-04-25), so loud failure is now mandatory.

### Smoketest
[`.github/workflows/openai_smoketest.yml`](../.github/workflows/openai_smoketest.yml) imports the live `CLASSIFICATION_SCHEMA` and `PROMPT`, sends a real classification request, and asserts the response conforms to the enums. Run on demand to verify the API contract end-to-end (catches strict-mode rejections, parser regressions, and Quality_Tier accidentally re-appearing).

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

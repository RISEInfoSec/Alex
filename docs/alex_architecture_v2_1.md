# Alex Architecture v2.1 (Gap-Closed Specification)

## Purpose
Alex v2.1 closes the design/specification gaps identified in the QA pass against the original requirements.

This is a **corrected package specification** for a comprehensive, high-quality, continuously updating research observatory for OSINT as it relates to cybersecurity and cyber investigations.

## What v2.1 fixes
Compared with v2, v2.1 explicitly adds:

- Google Scholar as a monitored discovery source (manual/assisted due automation constraints)
- Dimensions as a monitored discovery source
- GitHub as a monitored discovery source
- explicit journal targeting for:
  - Social Network Analysis and Mining
  - IEEE Security & Privacy
- source-specific discovery connectors/parsers as required implementation targets for:
  - IEEE
  - ACM
  - USENIX
  - DFRWS
  - FIRST
  - SANS
  - Black Hat
  - RAND
  - CSIS
  - Atlantic Council
  - NATO StratCom COE
  - Bellingcat
- a real review-queue generation requirement
- a real quality-gate implementation requirement
- a real citation-chain implementation requirement

## Core design principles
1. Comprehensive
2. High-quality
3. Auditable
4. Human-supervised at the edges
5. Prefer omission over questionable inclusion
6. Separate public corpus from provisional/review materials

---

## Discovery layer

### Academic discovery sources
Alex v2.1 must monitor and use:

- Google Scholar
- Semantic Scholar
- CORE
- BASE
- Dimensions
- OpenAlex
- Crossref
- arXiv
- Zenodo

### Research repositories and code ecosystems
Alex v2.1 must monitor and use:

- GitHub
- Zenodo
- arXiv

### Conference / security publication sources
Alex v2.1 must monitor and use:

- IEEE security conferences
- ACM digital investigation / security conferences
- USENIX
- Digital Forensics Research Conference (DFRWS)
- FIRST
- SANS Institute whitepapers / DFIR-related material
- Black Hat research archive

### Think-tank / policy / investigative publication sources
Alex v2.1 must monitor and use:

- RAND Corporation
- Center for Strategic and International Studies (CSIS)
- Bellingcat
- Atlantic Council
- NATO Strategic Communications Centre of Excellence

### Source-coverage note
Because some sources are difficult to automate directly (especially Google Scholar and some institutional sites), v2.1 permits a mixed model:

- API-based ingestion where possible
- RSS/feed parsing where available
- source-specific scraping/parsing where permitted
- manual/assisted monitoring queues where direct automation is not robust or appropriate

---

## Query families

The following query families must be maintained in config and used regularly:

- "open source intelligence"
- "OSINT methodology"
- "OSINT investigation"
- "social media intelligence"
- "digital investigation techniques"
- "threat intelligence collection"
- "internet investigation methods"
- "dark web intelligence"
- "OSINT research"
- "open source investigation"
- "cybersecurity"
- "cybercrime research"
- "cybercrime"
- "online threats"
- "APT"
- "advanced persistent threats"

---

## Citation chaining (mandatory)

Citation chaining is a required part of Alex v2.1.

### Backward chaining
For accepted seed papers and newly accepted high-value papers:
- inspect references cited by the paper

### Forward chaining
For accepted seed papers and newly accepted high-value papers:
- inspect works citing the paper

### Author chaining
For trusted and high-value papers:
- inspect other relevant publications by the same author(s)

### Citation graph sources
Use:
- Semantic Scholar citation graph
- OpenAlex reference / cited-by graph

### Output
Citation chaining must generate:
- additional discovery candidates
- provenance showing whether each candidate came from forward, backward, or author chaining

---

## Relevant journals and venue targeting

Alex v2.1 must explicitly target and monitor at minimum:

- Digital Investigation
- Intelligence and National Security
- Journal of Cybersecurity
- Computers & Security
- Social Network Analysis and Mining
- IEEE Security & Privacy

These journals should be represented in:
- venue whitelists
- journal target registries
- recurring discovery routines

---

## Quality-control layer

Quality must be assessed **before** adding work to the public corpus.

### Quality scoring dimensions
At minimum:
- Venue_Score
- Citation_Score
- Institution_Score
- Access_or_Usage_Score
- Relevance_Score
- Total_Quality_Score

### Inclusion policy
- Auto-include only when quality is sufficiently high
- Route uncertain papers to review queue
- Exclude questionable or unverifiable papers from the public corpus

### Human confirmation
Alex v2.1 must generate a review list for human confirmation when:
- venue quality is unclear
- metadata is incomplete
- relevance is ambiguous
- citation signal is too weak
- source cannot be verified automatically

### Prefer omission
If quality cannot be verified automatically, the paper should be omitted from the public corpus and routed to review instead.

---

## Review queue (mandatory)

Generate:
- `data/review_queue.csv`

Minimum fields:
- candidate_id
- title
- authors
- year
- venue
- doi
- source_url
- discovery_source
- inclusion_path
- citation_count
- venue_score
- institution_score
- relevance_score
- total_quality_score
- review_reason
- recommended_action

---

## Rejected candidates (mandatory)

Generate:
- `data/rejected_candidates.csv`

This should preserve:
- title
- source
- reason rejected
- score snapshot
- timestamp

Rejected items should not vanish silently.

---

## Metadata harvesting

For accepted candidates, harvest and normalize:
- DOI
- Authors
- Venue
- Abstract
- Source_URL
- Citation_Count
- Reference_Count (where available)

Preferred metadata sources:
- Crossref
- OpenAlex
- Semantic Scholar

Secondary resolvers:
- arXiv metadata
- Zenodo metadata
- trusted source-specific conference / think-tank pages

---

## LLM tagging

After metadata harvest (and post-harvest rescore), classify:
- Category — closed enum, 15 values, see [`docs/retrieval_gating_taxonomy.md`](retrieval_gating_taxonomy.md) §5
- Investigation_Type — closed enum, 11 values
- OSINT_Source_Types — closed enum, 14 values (list)
- Keywords — free-form (list)
- Tags — free-form (list)

Set independently of the LLM:
- `Seminal_Flag` — code-set, `TRUE` iff `citation_count >= 500`
- `Quality_Tier` — derived at publish time from `total_quality_score` (≥75 High, ≥60 Standard, else Exploratory)

Enforcement is via OpenAI structured outputs (`text.format = json_schema`, `strict=true`) — the model can't drift outside the enums. See [`alex/pipelines/classify.py`](../alex/pipelines/classify.py)::`CLASSIFICATION_SCHEMA`.

### Important constraint
LLM tagging may enrich structure, but it must not override verified bibliographic metadata.

---

## Public vs internal outputs

### Public corpus
- master accepted workbook
- `data/osint_cyber_papers.csv`
- `papers.json`

### Internal / operational outputs
- `data/discovery_candidates.csv`
- `data/review_queue.csv`
- `data/rejected_candidates.csv`
- `data/quality_metrics.csv`

The review queue and rejected candidates are internal governance artifacts unless deliberately published.

---

## Required workflows

Alex v2.1 requires the following workflow set:

1. `discover.yml`
2. `discover_manual_assist.yml`
3. `citation_chain.yml`
4. `quality_gate.yml`
5. `harvest.yml`
6. `harvest_all.yml`
7. `tag_new_papers.yml`
8. `rebuild_site.yml`
9. `pages.yml`

### Workflow purpose

#### discover.yml
Automated discovery from APIs, feeds, and configured sources.

#### discover_manual_assist.yml
Tracks sources that require manual/assisted review (especially Google Scholar and Dimensions).

#### citation_chain.yml
Expands from accepted seeds using citations, references, and author chaining.

#### quality_gate.yml
Scores and routes candidates into:
- accepted
- review queue
- rejected

#### harvest.yml / harvest_all.yml
Fetches authoritative metadata for accepted candidates.

#### tag_new_papers.yml
Applies taxonomy and discovery labels via LLM classification.

#### rebuild_site.yml
Rebuilds CSV + JSON.

#### pages.yml
Publishes the searchable site.

---

## Required scripts

Alex v2.1 requires the following implementation targets:

- `scripts/discover_new_papers.py`
- `scripts/discover_manual_assist.py`
- `scripts/citation_chain.py`
- `scripts/quality_gate.py`
- `scripts/harvest_osint_metadata.py`
- `scripts/llm_tag_new_papers.py`
- `scripts/rebuild_site_assets.py`

---

## Required config

Alex v2.1 must maintain:

- `config/source_registry.json`
- `config/query_registry.json`
- `config/journal_targets.json`
- `config/conference_targets.json`
- `config/thinktank_targets.json`
- `config/venue_whitelist.json`
- `config/venue_blacklist.json`
- `config/quality_weights.json`
- `config/manual_assist_sources.json`

---

## End state

When fully implemented, Alex v2.1 should:

- search the complete target source universe regularly
- use citation chaining
- apply quality scoring before publication
- maintain a human review queue
- exclude unverifiable / questionable material from the public corpus
- publish only the accepted, structured, searchable corpus

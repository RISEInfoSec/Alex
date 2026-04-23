# Alex v2.1.1 Production-Ready Package

Alex is a production-oriented discovery, evaluation, enrichment, and publishing pipeline for building a **high-quality OSINT + cybersecurity research corpus**.

## What this package does

It implements a practical end-to-end system for:

1. **Discovery** across multiple source families
2. **Citation chaining** using OpenAlex and Semantic Scholar
3. **Quality scoring** before public inclusion
4. **Authoritative metadata harvesting**
5. **LLM taxonomy tagging**
6. **Governance outputs** for review and rejection
7. **Static-site publication** via GitHub Pages

## Source families checked

### Academic indexes
- OpenAlex
- Crossref
- Semantic Scholar
- CORE
- BASE (manual-assist placeholder / ingestion adapter)
- Dimensions (manual-assist placeholder)

### Research repositories
- arXiv
- Zenodo
- GitHub

### Security conferences and archives
- IEEE
- ACM
- USENIX
- DFRWS
- FIRST
- SANS
- Black Hat

### Think-tank / investigative sources
- RAND
- CSIS
- Atlantic Council
- NATO Strategic Communications Centre of Excellence
- Bellingcat

## Query families used

Configured in `config/query_registry.json` and intended for recurring execution:

- open source intelligence
- OSINT methodology
- OSINT investigation
- social media intelligence
- digital investigation techniques
- threat intelligence collection
- internet investigation methods
- dark web intelligence
- OSINT research
- open source investigation
- cybersecurity
- cybercrime research
- cybercrime
- online threats
- APT
- advanced persistent threats

## Quality model

Alex scores candidates using:

- Venue score
- Citation score
- Institution score
- Usage / access score
- Relevance score

### Routing policy
- **>= 75**: auto-include
- **45–74.99**: review queue
- **< 45**: reject

Alex **prefers omission over contamination**. If quality cannot be verified, the record should not enter the public corpus.

## Citation chaining

Alex expands the corpus via:

- **backward chaining**: references cited by accepted seed papers
- **forward chaining**: papers citing accepted seed papers
- **author chaining**: related papers by trusted authors

Primary graph sources:
- OpenAlex
- Semantic Scholar

## Outputs

### Public outputs
- `data/osint_cyber_papers.csv`
- `data/papers.json`

### Internal governance outputs
- `data/discovery_candidates.csv`
- `data/review_queue.csv`
- `data/rejected_candidates.csv`
- `data/quality_metrics.csv`

## How to run

### 1. Install
```bash
python -m pip install -r requirements.txt
```

### 2. Set environment variables
```bash
export HARVEST_MAILTO="you@example.org"
export OPENAI_API_KEY="sk-..."
export OPENAI_MODEL="gpt-4o-mini"
```

### 3. Discover
```bash
python -m alex.cli discover
```

### 4. Citation-chain discovered candidates
```bash
python -m alex.cli chain
```

### 5. Score and route candidates
```bash
python -m alex.cli score
```

### 6. Harvest accepted candidates
```bash
python -m alex.cli harvest
```

### 7. LLM classify accepted candidates
```bash
python -m alex.cli classify
```

### 8. Rebuild public assets
```bash
python -m alex.cli publish
```

## GitHub Actions included

Pipeline workflows (each commits its output to `main`):

- `discover.yml` — scheduled Mon 03:23 UTC
- `citation_chain.yml` — chains from Discover
- `quality_gate.yml` — chains from Citation chain
- `harvest.yml` — manual dispatch only
- `harvest_all.yml` — scheduled Sun 03:31 UTC
- `classify.yml` — chains from Harvest / Harvest all
- `publish.yml` — chains from Classify
- `tag_new_papers.yml` — manual re-tag via LLM
- `rebuild_site.yml` — manual re-publish

Deployment and auxiliary:

- `pages.yml` — GitHub Pages deploy on push to `main`
- `discover_manual_assist.yml` — scheduled reminder for Google Scholar / Dimensions / BASE

### Data flow and cadence

```mermaid
flowchart TB
    classDef cron fill:#fef3c7,stroke:#f59e0b,color:#78350f
    classDef wf fill:#dbeafe,stroke:#3b82f6,color:#1e3a8a
    classDef data fill:#ede9fe,stroke:#8b5cf6,color:#4c1d95
    classDef deploy fill:#d1fae5,stroke:#10b981,color:#064e3b

    cronMon["⏰ Mon 03:23 UTC"]:::cron
    cronSun["⏰ Sun 03:31 UTC"]:::cron

    discover["Discover"]:::wf
    citation["Citation chain"]:::wf
    quality["Quality gate"]:::wf
    harvest["Harvest all metadata"]:::wf
    classify["Classify (LLM)"]:::wf
    publish["Publish assets"]:::wf
    pages["Pages deploy"]:::deploy

    dc[("discovery_candidates.csv")]:::data
    ac[("accepted_candidates.csv")]:::data
    ah[("accepted_harvested.csv")]:::data
    acl[("accepted_classified.csv")]:::data
    site[("data/papers.json<br/>data/osint_cyber_papers.csv")]:::data

    cronMon --> discover
    cronSun --> harvest

    discover -- workflow_run --> citation
    citation -- workflow_run --> quality
    harvest -- workflow_run --> classify
    classify -- workflow_run --> publish
    publish -- "git push main" --> pages

    discover -.writes.-> dc
    citation -.augments.-> dc
    dc -.reads.-> quality
    quality -.writes.-> ac
    ac -.reads.-> harvest
    harvest -.writes.-> ah
    ah -.reads.-> classify
    classify -.writes.-> acl
    acl -.reads.-> publish
    publish -.writes.-> site
    site -.fetched by frontend.-> pages
```

**Weekly cycle in practice:**

1. **Monday 03:23 UTC** — `Discover` fires, then auto-chains through `Citation chain` → `Quality gate`. New `data/accepted_candidates.csv` is produced.
2. **Sunday 03:31 UTC** — `Harvest all metadata` reads the accepted list and auto-chains through `Classify` → `Publish assets`.
3. **After publish pushes to `main`** — `pages.yml` deploys the refreshed `data/papers.json` to GitHub Pages.

The gap between discovery (Monday) and harvest (following Sunday) is intentional buffer for the Monday `Manual-assist discovery queue` reminder to be acted on — papers added by hand during the week are picked up by Sunday's run.

## Important operational notes

- Google Scholar and Dimensions are represented as **manual-assist / registry-backed sources**, because reliable direct automation is constrained by access, terms, or subscription.
- BASE and some conference / think-tank sources are handled through adapter registries and source-specific ingestion targets; connectors are provided as extensible modules.
- The package is designed to be **production-oriented**, but actual performance depends on API keys, quotas, and data-source availability.

See `docs/gap_analysis.md` for remaining operational constraints and how to address them.

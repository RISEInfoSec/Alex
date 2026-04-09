# Gap Analysis

This package is production-oriented and includes working code for:
- OpenAlex discovery
- Crossref discovery and DOI harvest
- Semantic Scholar discovery and citation access
- CORE discovery
- arXiv discovery
- Zenodo discovery
- GitHub repository discovery
- citation chaining workflow
- quality scoring workflow
- authoritative metadata harvest
- LLM classification wrapper
- publication pipeline

## Remaining constraints

### Google Scholar
Reason:
- direct reliable automation is constrained by scraping restrictions / anti-bot protections.

Resolution:
- keep Google Scholar in the monitored source registry and feed it into manual-assist workflows.

### Dimensions
Reason:
- API access is typically subscription-controlled.

Resolution:
- maintain it in manual-assist registry or integrate when licensed.

### BASE
Reason:
- source-specific integration may need custom endpoint / parser support depending on deployment context.

Resolution:
- add a BASE connector if stable endpoint access is available in your environment.

### Institution scoring
Current state:
- heuristic scoring implemented.
Better fix:
- integrate ROR or GRID mapping.

### Usage metrics
Current state:
- framework is present but external altmetric/download APIs are not wired in by default.
Better fix:
- integrate Altmetric, repository download stats, or OpenAlex-derived signals.

### LLM classification
Current state:
- working API wrapper included, but requires valid OPENAI_API_KEY and model access.

## QA verdict
This package closes the major design/spec gaps and includes executable code for core connectors and scorers.
Where a source cannot be robustly automated for policy or access reasons, that shortfall is called out and routed to manual-assist handling.

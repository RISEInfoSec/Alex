# Alex v2.1.1 Architecture

## Pipeline
1. Discovery from APIs and registries
2. Citation chaining
3. Quality gating
4. Metadata harvest
5. LLM classification
6. Publication

## Governance
- discovery_candidates.csv holds raw candidates
- review_queue.csv holds uncertain candidates
- rejected_candidates.csv holds excluded records
- accepted_classified.csv is the final internal accepted corpus
- osint_cyber_papers.csv and papers.json are public outputs

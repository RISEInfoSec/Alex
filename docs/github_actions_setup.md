# GitHub Actions Setup

## Repository credentials and variables

Set user-managed secrets in **Settings → Secrets and variables → Actions → Secrets**.
Keep key values out of source files, logs, issues and artifacts. Secret presence
alone does not establish current quota or permission to lift a provider hold.

| Name | Provisioning and purpose | Current workflow use |
| --- | --- | --- |
| `HARVEST_MAILTO` | A monitored project contact email; no provider registration is needed for this value. Sent in academic API User-Agent headers. | Discovery, citation chaining, harvest and APWG audits. |
| `OPEN_API_KEY` | Create a project API key in the [OpenAI API platform](https://platform.openai.com/); configure funding and limits there. This repository secret name is intentional. | Classification, tag-new-papers, the OpenAI smoketest and optional APWG classification; mapped to `OPENAI_API_KEY` in the runner. Review-branch paid workflows use the same mapping. |
| `OPENALEX_API_KEY` | Obtain a key through an OpenAlex account, following [OpenAlex authentication documentation](https://help.openalex.org/api/authentication/). Confirm actual account allowance before authorized use. | Discovery, citation chaining, harvest and APWG audits; governed by current `config/openalex_request_policy.json` and shared provider state. |
| `CORE_API_KEY` | Optional key from [CORE API services](https://core.ac.uk/services/api). | Mapped into discovery; CORE is currently disabled in `config/query_registry.json`. A key does not authorize enabling it. |
| `SEMANTIC_SCHOLAR_API_KEY` | Optional key requested through the [Semantic Scholar API](https://www.semanticscholar.org/product/api). Local code supports it for discovery, citation chaining and harvest. | The connector is disabled and current main workflows do not map this secret into their environment. Adding the secret alone does not activate the route. |
| `GITHUB_TOKEN` | Automatically issued by GitHub Actions; do not create a repository secret for it. | Repository/source reads and scoped workflow writes, deployment and failure reporting, according to each workflow's `permissions`. |

`OPENAI_MODEL` is an optional **Actions variable**, not a secret. Production
classification defaults to `gpt-4o-mini`; the smoketest explicitly uses that
model. Keep model/prompt/schema/input bindings when reusing paid responses.

## Enable GitHub Pages
1. **Settings → Pages**
2. Source: **GitHub Actions**

## Workflows

### Automated
- **`pipeline.yml`** — scheduled **Mon 03:23 UTC**. Separate dependent jobs run Discover → Citation chain → Quality gate → Harvest → Rescore → Classify → APWG audit → Publish → Pages deploy, followed by reporting. Downstream jobs check out current `main` to consume preceding stage commits. Complete discovery and successful prerequisite stages are required for publication; a green APWG job can still report provider-deferred coverage and is not proof of full source access.
- **`pages.yml`** — fires on push to `main`. Has `cancel-in-progress: true` so newer pushes supersede in-flight deploys (prevents queue wedge).
- **`discover_manual_assist.yml`** — Mon 04:05 UTC reminder for human-curated sources.

### Manual (`workflow_dispatch` only)
Single-stage debug tools — none of these auto-trigger anything else:

- `discover.yml`, `citation_chain.yml`, `quality_gate.yml`, `harvest.yml`, `classify.yml`, `publish.yml`
- `tag_new_papers.yml` — classify harvested inputs using the same paid ledger, remote reservations, response retention and ambiguous-send holds as `classify.yml`; not permission to replay prior paid work
- `rebuild_site.yml` — regenerate site assets from existing classified corpus
- `openai_smoketest.yml` — pre-flight canary; one OpenAI call, prints status / body / token usage

## Recommended first use
1. Provision the required secrets above; leave optional connectors disabled unless explicitly enabled within their existing authority and budgets.
2. Inspect current provider policies, owner holds, saved state and prior response evidence. A missing or ambiguous paid outcome requires reconciliation before another send.
3. When an actual new paid diagnostic is authorized and needed, **OpenAI smoketest** makes one call to check the current API/schema contract. Reuse retained matching evidence where possible; do not spend merely to replace an old red run with green.
4. Run **Pipeline** only when its current provider holds permit it. OpenAlex is presently paused; its earliest owner review time is not automatic resumption. See [weekly recovery rules](weekly_discovery_protocol.md).

## Actual outputs

The [README output inventory](../README.md#public-corpus-deployed-to-github-pages)
distinguishes public exports, internal corpus and intermediate working state.
`data/review_queue.csv` is produced by the quality gate and committed to `main`;
it is an intermediate review-tier list, not the Content Review human-decision queue.
Large candidate/quality/rescore files, provider checkpoints, harvest cache and paid
ledger live compressed on `pipeline-state`; use `scripts/state.sh pull` to read
them. Their absence from `main` does not mean a pipeline never completed.
`data/papers.json` and `data/osint_cyber_papers.csv` are the public exports;
`data/accepted_classified.csv` retains internal approved rows and technical holds.

## Troubleshooting

### Pages deploy stuck pending
The `github-pages` environment serializes deployments. If a deployment is left in `waiting` / `queued` / `in_progress` state (most often because an earlier run was force-cancelled), every new Pages deploy queues behind it. Detect and clear:

```bash
gh api 'repos/RISEInfoSec/Alex/deployments?environment=github-pages&per_page=100' --jq '.[].id' | \
  while read id; do
    state=$(gh api repos/RISEInfoSec/Alex/deployments/$id/statuses --jq '.[0].state')
    case "$state" in waiting|queued|in_progress) echo "stuck: $id state=$state";; esac
  done

gh api repos/RISEInfoSec/Alex/deployments/<id>/statuses -X POST -f state=inactive -f description="manual clear"
```

### Classify produces all `"Other"` categories
Historical silent fallback caused this symptom. Current classification fails on
missing credentials, network/HTTP errors, empty or invalid responses and quota
errors; it never fabricates `Other`. A real schema-valid model response can still
legitimately return `Other`. Inspect retained request/response evidence before
any paid retry; reconcile reserved or started requests whose outcomes are unknown.

# GitHub Actions Setup

## Required repository secrets
- **`HARVEST_MAILTO`** — contact email sent in User-Agent headers to academic APIs (politeness contract).
- **`OPEN_API_KEY`** — OpenAI API key. The workflow files map this onto the `OPENAI_API_KEY` env var; don't rename the secret.

## Required repository variables (optional)
- **`OPENAI_MODEL`** — overrides the default `gpt-4o-mini` for classification. Leave unset to use the default.

## Enable GitHub Pages
1. **Settings → Pages**
2. Source: **GitHub Actions**

## Workflows

### Automated
- **`pipeline.yml`** — scheduled **Mon 03:23 UTC**. Runs all seven stages (Discover → Citation chain → Quality gate → Harvest → Rescore → Classify → Publish) in one job, then deploys to Pages in a second job. The deploy job uses `actions/checkout@v4` with `ref: main` so it picks up commits the pipeline pushed during the same run.
- **`pages.yml`** — fires on push to `main`. Has `cancel-in-progress: true` so newer pushes supersede in-flight deploys (prevents queue wedge).
- **`discover_manual_assist.yml`** — Mon 04:05 UTC reminder for human-curated sources.

### Manual (`workflow_dispatch` only)
Single-stage debug tools — none of these auto-trigger anything else:

- `discover.yml`, `citation_chain.yml`, `quality_gate.yml`, `harvest.yml`, `classify.yml`, `publish.yml`
- `tag_new_papers.yml` — re-tag already-harvested papers via LLM
- `rebuild_site.yml` — regenerate site assets from existing classified corpus
- `openai_smoketest.yml` — pre-flight canary; one OpenAI call, prints status / body / token usage

## Recommended first use
1. Create both repository secrets above.
2. Trigger **`OpenAI smoketest`** to confirm the OpenAI account is funded and the key is accepted.
3. Trigger **`Pipeline`** (or wait for the Monday cron) for a full end-to-end run.

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
Symptom of OpenAI `insufficient_quota` returns prior to the 2026-04-25 fix. Current behavior: `call_openai()` raises `OpenAIQuotaError` on account-level errors and the run aborts loudly. If you see this, run the smoketest to confirm the cause and top up the account before re-triggering Classify.

# GitHub Actions Setup

## Required secret
Create repository secret:
- `HARVEST_MAILTO`

## Enable Pages
- Settings → Pages
- Source: GitHub Actions

## Workflows
- **Discover**: scheduled Mon 03:23 UTC. Kicks off the full weekly pipeline — chains through Citation chain → Quality gate → Harvest → Classify → Publish → Pages deploy via `workflow_run` on success.
- **Harvest**: chained from Quality gate; also runs on manual dispatch.
- **Tag new papers / Rebuild site assets**: manual dispatch only, for ad-hoc re-tagging or republishing.
- **Pages**: deploys the site on any push to `main`.

## Recommended first use
Manually dispatch **Discover** once after uploading the repository to seed the pipeline end-to-end.

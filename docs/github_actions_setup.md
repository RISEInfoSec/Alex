# GitHub Actions Setup

## Required secret
Create repository secret:
- `HARVEST_MAILTO`

## Enable Pages
- Settings → Pages
- Source: GitHub Actions

## Workflows
- **Harvest bibliographic metadata**: run specific ID ranges manually
- **Harvest all metadata automatically**: runs through the whole corpus in sequential 25-record batches
- **Deploy GitHub Pages**: publishes the site

## Recommended first use
Run **Harvest all metadata automatically** once after uploading the repository.

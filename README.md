# OSINT + Cybersecurity Research Library

This package includes GitHub Actions to:

- harvest bibliographic metadata in **manual batches**
- run an **automatic full enrichment pass** across all records in sequential batches
- deploy the site to **GitHub Pages**

## Workflows

- `.github/workflows/harvest.yml` — manual batch harvester
- `.github/workflows/harvest_all.yml` — automatically runs all batches in sequence
- `.github/workflows/pages.yml` — deploys GitHub Pages

## Required setup

Add repository secret:

- `HARVEST_MAILTO`

Then set **Settings → Pages → Source** to **GitHub Actions**.

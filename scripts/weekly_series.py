"""Start or resume one isolated seven-day discovery window."""
from __future__ import annotations

import argparse
from datetime import date, datetime, timedelta, timezone
import json
import os
from pathlib import Path
import subprocess

from alex.pipelines import discovery
from alex.utils.discovery_checkpoint import DiscoveryIncomplete, atomic_json

FIRST_END = date(2026, 11, 23)
EXTRA_END = date(2026, 11, 24)
EXTRA_CRON = '0 8 24 11 *'
SERIES = 'weekly-series-v1'
LEGACY_COMMIT = '4d6467b1984da1903b9d4262f92b2d7e38cfeddc'


def window_manifest(end: date):
    if (end.weekday() != 0 and end != EXTRA_END) or not FIRST_END <= end <= datetime.now(timezone.utc).date():
        raise ValueError('Choose a scheduled ending date from the first series window through today.')
    return {
        'series': SERIES,
        'window': {'from_date': (end - timedelta(days=7)).isoformat(), 'until_date': end.isoformat()},
        'historical_pipeline': {'status': 'incomplete', 'state_commit': LEGACY_COMMIT,
                                'reason': 'citation_and_harvest_completion_unverified'},
        'held_sources': {'OpenAlex': ['search', 'DOI singleton', 'abstract enrichment']} if end == FIRST_END else {},
        'publication_authorized': False,
    }


def collect(end: date):
    manifest = window_manifest(end)
    branch = SERIES + '/' + end.isoformat()
    os.environ.update(STATE_BRANCH=branch, ALEX_DISCOVERY_SYNC='1',
                      ALEX_DISCOVERY_PASS_ID=os.environ['GITHUB_RUN_ID'] + ':' + os.environ['GITHUB_RUN_ATTEMPT'],
                      ALEX_OPENALEX_STATE_PATH='data/discovery_openalex_state.json')
    data = Path('data')
    subprocess.run(['bash', 'scripts/state.sh', 'open-series'], check=True)
    marker = data / 'series_window.json'
    if marker.exists():
        if json.loads(marker.read_text()) != manifest:
            raise ValueError('Series window provenance changed')
    else:
        atomic_json(marker, manifest)
        subprocess.run(['bash', 'scripts/state.sh', 'push', 'Initialize isolated discovery window'], check=True)
    try:
        discovery.run(series=manifest)
    except DiscoveryIncomplete:
        print('Checkpoint retained. At least one enabled source did not finish.', flush=True)
        raise
    finally:
        path = data / 'discovery_run_receipt.json'
        if path.exists():
            receipt = json.loads(path.read_text())
            if receipt.get('orchestration_pass_id') == os.environ['ALEX_DISCOVERY_PASS_ID']:
                print(json.dumps({k: receipt.get(k) for k in ('series', 'window', 'status', 'completed_tasks',
                    'new_candidates', 'deferred_tasks', 'actual_request_count', 'openalex_request_count',
                    'candidate_file_sha256')}, sort_keys=True), flush=True)


def scheduled_window(created: str, cron: str, requested: str = '') -> date | None:
    launched = datetime.fromisoformat(created.replace('Z', '+00:00')).astimezone(timezone.utc).date()
    if cron == EXTRA_CRON:
        return EXTRA_END if launched == EXTRA_END else None
    if cron and cron != '23 3 * * 1':
        raise ValueError('Unrecognized weekly schedule')
    if requested and not cron:
        return date.fromisoformat(requested)
    return launched - timedelta(days=launched.weekday())


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--week-ending', default='')
    parser.add_argument('--run-created-at', required=True)
    parser.add_argument('--cron', default='')
    args = parser.parse_args()
    end = scheduled_window(args.run_created_at, args.cron, args.week_ending)
    if end is None:
        print('The one-time November 24 schedule has expired.')
    else:
        collect(end)

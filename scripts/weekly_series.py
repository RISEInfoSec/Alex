"""Start or resume one isolated Monday-to-Monday discovery window."""
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
SERIES = 'weekly-series-v1'
LEGACY_COMMIT = '4d6467b1984da1903b9d4262f92b2d7e38cfeddc'


def window_manifest(end: date):
    if end.weekday() != 0 or end < FIRST_END or end > datetime.now(timezone.utc).date():
        raise ValueError('Choose a Monday from the first series window through today.')
    return {
        'series': SERIES,
        'window': {'from_date': (end - timedelta(days=7)).isoformat(), 'until_date': end.isoformat()},
        'historical_pipeline': {'status': 'incomplete', 'state_commit': LEGACY_COMMIT,
                                'reason': 'citation_and_harvest_completion_unverified'},
        'held_sources': {'OpenAlex': ['search', 'DOI singleton', 'abstract enrichment']},
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


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--week-ending', default='')
    parser.add_argument('--run-created-at', required=True)
    args = parser.parse_args()
    launched = datetime.fromisoformat(args.run_created_at.replace('Z', '+00:00')).astimezone(timezone.utc).date()
    collect(date.fromisoformat(args.week_ending) if args.week_ending else launched - timedelta(days=launched.weekday()))

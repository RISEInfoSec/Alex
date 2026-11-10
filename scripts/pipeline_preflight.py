"""Check existing pipeline checkpoints before scheduled discovery can send requests."""
from __future__ import annotations

import json
import re
from pathlib import Path

from alex.utils.harvest_checkpoint import digest, file_sha256, verified_completed_output
from scripts.citation_guard import _read


def verify(root: Path):
    data = root / 'data'
    source = data / 'discovery_candidates.csv'
    guard = _read(data / 'citation_run_guard.json')
    expected = guard.get('quality_output_sha256', guard.get('output_sha256'))
    if (guard.get('status') != 'complete' or not source.is_file()
            or not re.fullmatch(r'[0-9a-f]{64}', str(expected or ''))
            or file_sha256(source) != expected):
        raise RuntimeError('Citation state unverified; reconcile before discovery')

    checkpoint = data / 'harvest_response_cache.jsonl'
    if checkpoint.with_name(checkpoint.name + '.uncertain').exists():
        raise RuntimeError('Harvest state uncertain; reconcile before discovery')
    try:
        with checkpoint.open(encoding='utf-8') as stream:
            first = next(stream)
            header = json.loads(first)
            if (not first.endswith('\n') or header.get('schema_version') != 1
                    or not re.fullmatch(r'[0-9a-f]{64}', str(header.get('input_sha256', '')))):
                raise ValueError
            complete = False
            output_sha = None
            for line in stream:
                if not line.endswith('\n'):
                    raise ValueError
                record = json.loads(line)
                event = record.get('event')
                if event == 'response':
                    payload = {k: record[k] for k in ('request_sha256', 'response')}
                    if digest(payload) != record.get('sha256') or payload['response'] is None:
                        raise ValueError
                    complete = False
                elif event == 'not_found':
                    payload = {k: record[k] for k in ('request_sha256', 'http_status', 'evidence')}
                    if payload['http_status'] != 404 or digest(payload) != record.get('sha256'):
                        raise ValueError
                    complete = False
                elif event in ('begin', 'complete'):
                    complete = event == 'complete'
                    output_sha = record.get('output_sha256') if complete else None
                    if complete and digest({'event': 'complete', 'output_sha256': output_sha}) != record.get('sha256'):
                        raise ValueError
                else:
                    raise ValueError
        accepted = data / 'accepted_candidates.csv'
        if (not complete or not accepted.is_file() or file_sha256(accepted) != header['input_sha256']
                or not re.fullmatch(r'[0-9a-f]{64}', str(output_sha or ''))
                or not verified_completed_output(data / 'accepted_harvested.csv', output_sha,
                                                  header['input_sha256'])):
            raise ValueError
    except (OSError, ValueError, TypeError, KeyError, AttributeError, StopIteration):
        raise RuntimeError('Harvest state unverified; reconcile before discovery') from None


if __name__ == '__main__':
    try:
        verify(Path.cwd())
    except RuntimeError as exc:
        raise SystemExit(str(exc)) from None

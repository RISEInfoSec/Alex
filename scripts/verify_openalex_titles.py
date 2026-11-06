"""Three bounded, read-only regression queries; no candidates or publications."""
import json
import os
import re
from pathlib import Path
import time

from alex.connectors import openalex
from alex.utils.http import HttpClient

TITLES = (
    'G*Power 3: A flexible statistical power analysis program for the social, behavioral, and biomedical sciences',
    'Statistical power analyses using G*Power 3.1: Tests for correlation and regression analyses',
    'ON THE PRICING OF CORPORATE DEBT: THE RISK STRUCTURE OF INTEREST RATES*',
)


class Probe(HttpClient):
    def __init__(self):
        super().__init__(mailto=os.getenv('HARVEST_MAILTO', ''))
        self.events = []
        self.deadline = time.monotonic() + 90

    def _send_request(self, url, **kwargs):
        if len(self.events) >= 3 or time.monotonic() + 20 > self.deadline:
            raise RuntimeError('Diagnostic request/runtime limit')
        event = {'http_status': None}
        self.events.append(event)
        try:
            response = super()._send_request(url, **kwargs)
            event['http_status'] = response.status_code
            return response
        except Exception as exc:
            event['error_type'] = type(exc).__name__
            raise


def main():
    client = Probe()
    proof = {'run_id': os.getenv('GITHUB_RUN_ID'), 'sha': os.getenv('GITHUB_SHA'),
             'status': 'blocked', 'requests': client.events, 'cases': []}
    try:
        for title in TITLES:
            before = len(client.events)
            matches = openalex.search(client, title, os.getenv('HARVEST_MAILTO', ''),
                                       per_page=3, literal_title=True)
            normalized = lambda text: re.sub(r'\W', '', text.casefold())
            matched = [work.get('id') for work in matches
                       if normalized(work.get('title') or '') == normalized(title)]
            proof['cases'].append({'title': title, 'returned_works': len(matches),
                                   'matching_work_ids': matched})
            if (len(client.events) != before + 1 or client.events[-1]['http_status'] != 200
                    or not matched):
                return 1  # Stop on any failure/hold; never retry the original bad query.
        proof['status'] = 'complete'
        return 0
    finally:
        output = Path('.cache/openalex-title-verification.json')
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(proof, indent=2) + '\n')
        print(json.dumps(proof))


if __name__ == '__main__':
    raise SystemExit(main())

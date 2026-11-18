import json

import pytest

from alex.utils.harvest_checkpoint import digest, file_sha256
from scripts.reconcile_saved_crossref import reconcile


def event(doi, response=None):
    request = json.dumps({'url': f'https://api.crossref.org/works/{doi}', 'params': {}, 'headers': {}}, sort_keys=True)
    payload = {'request_sha256': digest(request)}
    if response is None:
        payload.update(http_status=404, evidence={'source': 'fixture'})
        kind = 'not_found'
    else:
        payload['response'] = {'message': {'DOI': response}}
        kind = 'response'
    return {'event': kind, **payload, 'sha256': digest(payload)}


def write_checkpoint(path, input_csv, events):
    rows = [{'schema_version': 1, 'input_sha256': file_sha256(input_csv)}, {'event': 'begin'},
            *events, {'event': 'complete'}]
    path.write_text(''.join(json.dumps(row) + '\n' for row in rows))


def test_saved_outcomes_are_independent_of_legacy_completion(tmp_path):
    csv = tmp_path / 'input.csv'
    csv.write_text('doi\n10.1234/ok\n10.1234/mismatch\n10.1234/missing\n10.1234/404\n10.5281/archive\n')
    checkpoint = tmp_path / 'saved.jsonl'
    write_checkpoint(checkpoint, csv, [event('10.1234/ok', '10.1234/OK'),
                                     event('10.1234/mismatch', '10.1234/other'), event('10.1234/404')])
    report = reconcile(csv, checkpoint)
    assert report['outcomes'] == {'verified_response': 1, 'retained_not_found': 1, 'missing': 1, 'identity_unverified': 1}
    assert report['provider_requests'] == 0


@pytest.mark.parametrize('fault', ['input_hash', 'response_hash', 'conflict'])
def test_changed_or_conflicting_saved_outcomes_fail_closed(tmp_path, fault):
    csv = tmp_path / 'input.csv'
    csv.write_text('doi\n10.1234/ok\n')
    checkpoint = tmp_path / 'saved.jsonl'
    events = [event('10.1234/ok', '10.1234/ok')]
    if fault == 'response_hash':
        events[0]['response']['message']['DOI'] = '10.1234/changed'
    elif fault == 'conflict':
        events.append(event('10.1234/ok'))
    write_checkpoint(checkpoint, csv, events)
    if fault == 'input_hash':
        csv.write_text('doi\n10.1234/other\n')
    with pytest.raises(ValueError, match='harvest input|hash does not match|conflicting outcomes'):
        reconcile(csv, checkpoint)

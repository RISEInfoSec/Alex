import json

import pytest

from alex.utils.harvest_checkpoint import digest, file_sha256
from scripts.reconcile_saved_crossref import reconcile, write_manifest


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


def test_audit_is_input_bound_preserves_duplicates_and_never_authorizes_release(tmp_path, monkeypatch):
    import requests
    def deny_network(*args, **kwargs):
        raise AssertionError('Reconciliation must not send any provider request')
    monkeypatch.setattr(requests.sessions.Session, 'request', deny_network)
    csv = tmp_path / 'input.csv'
    csv.write_text('doi\n10.1234/ok\n10.1234/ok\n10.1234/mismatch\n10.1234/missing\n10.1234/404\n10.5281/skip\n')
    checkpoint = tmp_path / 'saved.jsonl'
    write_checkpoint(checkpoint, csv, [event('10.1234/ok', '10.1234/OK'),
                                     event('10.1234/mismatch', '10.1234/other'), event('10.1234/404')])
    original = (csv.read_bytes(), checkpoint.read_bytes())
    report = reconcile(csv, checkpoint, include_records=True)
    assert [r['input_record_index'] for r in report['records']] == [0, 1, 2, 3, 4]
    assert report['records'][0]['request_sha256'] == report['records'][1]['request_sha256']
    assert report['records'][2]['returned_doi'] == '10.1234/other'
    assert report['records'][3]['outcome_sha256'] is None
    assert report['input_sha256'] == file_sha256(csv)
    assert report['checkpoint_sha256'] == file_sha256(checkpoint)
    assert not any(report[k] for k in ('collection_complete', 'publication_authorized', 'replay_authorized'))
    assert original == (csv.read_bytes(), checkpoint.read_bytes())
    manifest = tmp_path / 'audit.json'
    write_manifest(manifest, report)
    saved = json.loads(manifest.read_text())
    assert saved['sha256'] == digest(saved['report'])
    for path in [manifest, csv, checkpoint]:
        with pytest.raises(FileExistsError):
            write_manifest(path, report)
    assert original == (csv.read_bytes(), checkpoint.read_bytes())


@pytest.mark.parametrize('fault', ['uncertain', 'input_changed', 'checkpoint_changed', 'uncertain_after_read'])
def test_audit_rejects_uncertainty_or_changed_inputs(tmp_path, monkeypatch, fault):
    from scripts import reconcile_saved_crossref as audit
    csv = tmp_path / 'input.csv'
    csv.write_text('doi\n10.1234/ok\n')
    checkpoint = tmp_path / 'saved.jsonl'
    write_checkpoint(checkpoint, csv, [event('10.1234/ok', '10.1234/ok')])
    marker = checkpoint.with_name(checkpoint.name + '.uncertain')
    if fault == 'uncertain':
        marker.write_text('{}')
    else:
        original = audit._events
        def changed(*args):
            result = original(*args)
            if fault == 'input_changed':
                csv.write_text('doi\n10.1234/other\n')
            elif fault == 'checkpoint_changed':
                with checkpoint.open('a') as stream:
                    stream.write('{"event":"begin"}\n')
            else:
                marker.write_text('{}')
            return result
        monkeypatch.setattr(audit, '_events', changed)
    with pytest.raises(ValueError, match='uncertain|input changed'):
        reconcile(csv, checkpoint, include_records=True)

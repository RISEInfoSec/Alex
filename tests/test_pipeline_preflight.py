import json

import pytest

from alex.utils.harvest_checkpoint import digest, file_sha256
from scripts import citation_guard, pipeline_preflight


@pytest.fixture
def ready(tmp_path):
    data = tmp_path / 'data'
    data.mkdir()
    source = data / 'discovery_candidates.csv'
    source.write_text('title\nSynthetic\n')
    citation_guard._write(data / 'citation_run_guard.json', {
        'schema_version': 1, 'status': 'complete', 'output_sha256': file_sha256(source)})
    output = data / 'accepted_harvested.csv'
    output.write_text('title\nSynthetic output\n')
    accepted = data / 'accepted_candidates.csv'
    accepted.write_text('title\nSynthetic input\n')
    response = {'request_sha256': '1'*64, 'response': {'message': {}}}
    output_sha = file_sha256(output)
    records = [{'schema_version': 1, 'input_sha256': file_sha256(accepted)}, {'event': 'begin'},
               {'event': 'response', **response, 'sha256': digest(response)},
               {'event': 'complete', 'output_sha256': output_sha,
                'sha256': digest({'event': 'complete', 'output_sha256': output_sha})}]
    (data / 'harvest_response_cache.jsonl').write_text(''.join(json.dumps(x)+'\n' for x in records))
    return tmp_path


def test_preflight_accepts_verified_checkpoints(ready):
    pipeline_preflight.verify(ready)


def test_preflight_rejects_missing_or_changed_citation(ready):
    (ready / 'data/discovery_candidates.csv').write_text('title\nUnexpected\n')
    with pytest.raises(RuntimeError, match='Citation state unverified'):
        pipeline_preflight.verify(ready)
    (ready / 'data/citation_run_guard.json').unlink()
    with pytest.raises(RuntimeError, match='Citation guard invalid'):
        pipeline_preflight.verify(ready)


@pytest.mark.parametrize('failure', ['uncertain', 'legacy', 'corrupt_response', 'changed_output', 'changed_input', 'incomplete'])
def test_preflight_rejects_uncertain_harvest(ready, failure):
    data = ready / 'data'
    path = data / 'harvest_response_cache.jsonl'
    records = [json.loads(line) for line in path.read_text().splitlines()]
    if failure == 'uncertain':
        (data / 'harvest_response_cache.jsonl.uncertain').write_text('{}')
    elif failure == 'legacy':
        records[-1] = {'event': 'complete'}
    elif failure == 'corrupt_response':
        records[2]['response'] = {'message': {'changed': True}}
    elif failure == 'changed_output':
        (data / 'accepted_harvested.csv').write_text('changed')
    elif failure == 'changed_input':
        (data / 'accepted_candidates.csv').write_text('changed')
    elif failure == 'incomplete':
        records.append({'event': 'begin'})
    path.write_text(''.join(json.dumps(x)+'\n' for x in records))
    with pytest.raises(RuntimeError, match='Harvest state'):
        pipeline_preflight.verify(ready)


def test_preflight_accepts_verified_rescore_lineage(ready):
    data = ready / 'data'
    output = data / 'accepted_harvested.csv'
    prior = file_sha256(output)
    output.write_text('title\nRescored synthetic\n')
    (data / '.harvest_output_lineage.json').write_text(json.dumps({
        'schema_version': 1, 'harvest_input_sha256': file_sha256(data / 'accepted_candidates.csv'),
        'harvest_output_sha256': prior, 'rescore_output_sha256': file_sha256(output)}))
    pipeline_preflight.verify(ready)

"""Restore DOI-bound type evidence from a completed harvest, without source calls."""
from __future__ import annotations
import hashlib
import json

import pandas as pd

from alex.metadata_holds import canonical_doi
from alex.utils.harvest_checkpoint import digest
from alex.utils.text import clean


def restore_crossref_types(frame, root):
    path = root / 'data/harvest_response_cache.jsonl'
    if not path.exists():
        return frame  # Older/local inputs may have no response checkpoint.
    input_path = root / 'data/accepted_candidates.csv'
    input_bytes = input_path.read_bytes()
    candidates = pd.read_csv(input_path)
    requests = {}
    for doi in candidates.get('doi', []):
        doi = clean(doi)
        if doi:
            url = 'https://api.crossref.org/works/' + doi
            key = json.dumps({'url':url,'params':{},'headers':{}},sort_keys=True)
            requests[digest(key)] = (canonical_doi(doi), url)
    types = {}
    complete = False
    with path.open(encoding='utf-8') as stream:
        header = json.loads(next(stream))
        if header.get('schema_version') != 1 or header.get('input_sha256') != hashlib.sha256(input_bytes).hexdigest():
            raise ValueError('Harvest type checkpoint belongs to another input')
        for line in stream:
            if not line.endswith('\n'):
                raise ValueError('Truncated harvest type evidence')
            record = json.loads(line)
            event = record['event']
            if event == 'response':
                payload = {k:record[k] for k in ('request_sha256','response')}
                if record['response'] is None or digest(payload) != record['sha256']:
                    raise ValueError('Harvest response integrity failed')
                complete = False
                if record['request_sha256'] not in requests:
                    continue
                doi, url = requests[record['request_sha256']]
                message = record['response'].get('message', {})
                if canonical_doi(message.get('DOI', '')) != doi:
                    raise ValueError('Harvest type response DOI mismatch')
                if message.get('type') is not None and not isinstance(message['type'], str):
                    raise ValueError('Invalid retained Crossref document type')
                kind = clean(message.get('type')).casefold()
                if kind:
                    if doi in types and types[doi]['kind'] != kind:
                        raise ValueError('Conflicting retained Crossref type evidence')
                    types[doi] = {'kind':kind,'source':url,'sha256':record['sha256']}
            elif event == 'not_found':
                payload = {k:record[k] for k in ('request_sha256','http_status','evidence')}
                if record['http_status'] != 404 or digest(payload) != record['sha256']:
                    raise ValueError('Harvest not-found integrity failed')
                complete = False
            elif event in ('begin','complete'):
                complete = event == 'complete'
            else:
                raise ValueError('Unknown harvest evidence record')
    if not complete:
        raise ValueError('Harvest type evidence is incomplete; do not rescore partial work')
    result = frame.copy()
    fields = ('harvest_crossref_type','harvest_crossref_type_source','harvest_crossref_type_evidence_sha256')
    for field in fields:
        result[field] = result[field].astype(object) if field in result else pd.Series('',index=result.index,dtype=object)
    restored = 0
    for index, row in result.iterrows():
        proof = types.get(canonical_doi(row.get('doi', '')))
        if proof is None:
            continue
        old_type = clean(row.get('harvest_crossref_type')).casefold()
        if old_type and old_type != proof['kind']:
            raise ValueError('Harvested row contradicts retained Crossref type')
        for field, value in zip(fields,(proof['kind'],proof['source'],proof['sha256'])):
            result.at[index,field] = value
        restored += 1
    print(f'Restored source type evidence for {restored} rows from retained Crossref responses')
    return result

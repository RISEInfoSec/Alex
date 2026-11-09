"""Restore DOI-bound type evidence from a completed harvest, without source calls."""
from __future__ import annotations
import hashlib
import json

import pandas as pd

from alex.metadata_holds import canonical_doi
from alex.utils.harvest_checkpoint import digest, file_sha256
from alex.utils.text import clean, strip_html_tags


def _title(value):
    return strip_html_tags(value).casefold()


def restore_crossref_types(frame, root):
    path = root / 'data/harvest_response_cache.jsonl'
    if not path.exists():
        return frame  # Older/local inputs may have no response checkpoint.
    input_path = root / 'data/accepted_candidates.csv'
    input_bytes = input_path.read_bytes()
    candidates = pd.read_csv(input_path)
    requests = {}
    for _, candidate in candidates.iterrows():
        doi = clean(candidate.get('doi'))
        if doi:
            url = 'https://api.crossref.org/works/' + doi
            key = json.dumps({'url':url,'params':{},'headers':{}},sort_keys=True)
            request = requests.setdefault(digest(key), (canonical_doi(doi), url, set()))
            request[2].add(_title(candidate.get('title')))
    types = {}
    complete = False
    completed_output_sha256 = None
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
                requested_doi, url, titles = requests[record['request_sha256']]
                message = record['response'].get('message', {})
                doi = canonical_doi(message.get('DOI', ''))
                alias_title = None
                if doi != requested_doi:
                    # Harvest already adopted the DOI returned by this exact
                    # response. Bind its type only to that returned DOI and
                    # the same source title, never infer a general DOI alias.
                    returned_titles = message.get('title', [])
                    if not isinstance(returned_titles, list):
                        raise ValueError('Invalid Crossref alias title evidence')
                    matches = {_title(t) for t in returned_titles if isinstance(t, str)} & titles - {''}
                    if not doi.startswith('10.') or len(matches) != 1:
                        raise ValueError('Harvest type response DOI mismatch')
                    alias_title = matches.pop()
                    matching = frame[frame['doi'].map(canonical_doi) == doi]
                    if matching.empty or not all(_title(t) == alias_title for t in matching['title']):
                        raise ValueError('Returned Crossref DOI/title not present in harvested rows')
                if message.get('type') is not None and not isinstance(message['type'], str):
                    raise ValueError('Invalid retained Crossref document type')
                kind = clean(message.get('type')).casefold()
                if kind:
                    if doi in types and types[doi]['kind'] != kind:
                        raise ValueError('Conflicting retained Crossref type evidence')
                    types[doi] = {'kind':kind,'source':url,'sha256':record['sha256'],
                                  'requested_doi':requested_doi, 'alias_title':alias_title}
            elif event == 'not_found':
                payload = {k:record[k] for k in ('request_sha256','http_status','evidence')}
                if record['http_status'] != 404 or digest(payload) != record['sha256']:
                    raise ValueError('Harvest not-found integrity failed')
                complete = False
            elif event in ('begin','complete'):
                complete = event == 'complete'
                completed_output_sha256 = record.get('output_sha256') if complete else None
                if complete and digest({'event':'complete', 'output_sha256':completed_output_sha256}) != record.get('sha256'):
                    raise ValueError('Harvest completion integrity failed')
            else:
                raise ValueError('Unknown harvest evidence record')
    if not complete:
        raise ValueError('Harvest type evidence is incomplete; do not rescore partial work')
    output = root / 'data/accepted_harvested.csv'
    if (not isinstance(completed_output_sha256, str) or not output.is_file()
            or file_sha256(output) != completed_output_sha256):
        raise ValueError('Harvest output does not match completed evidence')
    result = frame.copy()
    fields = ('harvest_crossref_type','harvest_crossref_type_source','harvest_crossref_type_evidence_sha256',
              'harvest_crossref_requested_doi')
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
        if proof['alias_title'] and _title(row.get('title')) != proof['alias_title']:
            raise ValueError('Harvested alias title contradicts retained Crossref response')
        for field, value in zip(fields,(proof['kind'],proof['source'],proof['sha256'],proof['requested_doi'])):
            result.at[index,field] = value
        restored += 1
    print(f'Restored source type evidence for {restored} rows from retained Crossref responses')
    return result

"""Small publication index built from the exact corpus in each Pages artifact."""
from __future__ import annotations
import csv
import hashlib
import json
from datetime import datetime, timezone


def build_index(rows, papers):
    records = {}
    for row in rows:
        cid, content = row.get('review_candidate_id'), row.get('review_content_sha256')
        if not cid or not content:
            continue
        expected = {'title':row.get('title',''), 'author':row.get('authors',''),
                    'summary':row.get('abstract',''), 'source_url':row.get('source_url',''),
                    'doi':row.get('doi',''), 'category':row.get('Category',''),
                    'investigation_type':row.get('Investigation_Type','')}
        matches = [p for p in papers if all(p.get(k, '') == v for k,v in expected.items())
                   and float(p.get('year') or 0) == float(row.get('year') or 0)]
        if len(matches) > 1 or cid in records:
            raise ValueError('Ambiguous publication identity: ' + cid)
        if matches:
            records[cid] = {'content_sha256':content, 'status':'published',
                            'public_record_id':matches[0]['id']}
    return records


def write_index(root, destination):
    source = root / 'data/accepted_classified.csv'
    with source.open(newline='', encoding='utf-8') as stream:
        rows = list(csv.DictReader(stream))
    raw = (root/'data/papers.json').read_bytes()
    value = {'schema_version':1, 'generated_at':datetime.now(timezone.utc).isoformat(),
             'papers_sha256':hashlib.sha256(raw).hexdigest(),
             'records':build_index(rows, json.loads(raw))}
    destination.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

"""Apply a digest-bound, explicitly approved Content Review release additively."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit
from alex.utils.text import normalize_title

GATES = ('format', 'access', 'metadata', 'duplicates', 'quality', 'schema', 'taxonomy',
         'completed_submission_integrity', 'final_source_revalidation')
HASH_FIELDS = ('title', 'authors', 'year', 'doi', 'source_url', 'abstract', 'document_type')


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def identities(row):
    doi = str(row.get('doi') or '').strip().lower().removeprefix('https://doi.org/').removeprefix('http://doi.org/').removeprefix('doi:')
    url = urlsplit(str(row.get('source_url') or '').strip())
    canonical = (url.netloc.lower() + url.path.rstrip('/')) if url.netloc else ''
    return {x for x in ('doi:' + doi if doi else '', 'url:' + canonical if canonical else '',
                       'title:' + normalize_title(row.get('title', ''))) if x}


def apply_release(manifest, corpus, receipt, write=False):
    data = json.loads(Path(manifest).read_text())
    records = data['records']
    if (data.get('publication_approved') is not True or not data.get('approval_basis')
            or len(records) != data['expected_records'] or digest(records) != data['records_sha256']):
        raise ValueError('Release authorization or digest mismatch')
    if len({r['candidate_id'] for r in records}) != len(records):
        raise ValueError('Duplicate release identity')
    for r in records:
        target = r['target']
        reviewed = {k: r['document_type'] if k == 'document_type' else target.get(k, '') for k in HASH_FIELDS}
        if (r['decision'] != 'approved' or r['document_type'] != 'research_paper'
                or digest(reviewed) != r['content_sha256'] or not r['submission']['payload_hash']):
            raise ValueError('Reviewed content or decision mismatch')
        for gate in GATES:
            c = r['checks'][gate]
            if c['status'] != 'passed' or c['content_sha256'] != r['content_sha256'] or not c['checked_at'] or not c['evidence_sha256']:
                raise ValueError('Missing, stale or held gate: ' + gate)
    corpus, receipt = Path(corpus), Path(receipt)
    with corpus.open(newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f); fields = list(reader.fieldnames); existing = list(reader)
    if receipt.exists():
        prior = json.loads(receipt.read_text())
        if prior['records_sha256'] != data['records_sha256'] or prior['release_id'] != data['release_id']:
            raise ValueError('Receipt mismatch')
        for r in records:
            found = [v for v in existing if v.get('review_candidate_id') == r['candidate_id']]
            if len(found) != 1 or any(found[0].get(k, '') != ('' if v is None else str(v)) for k, v in r['target'].items()):
                raise ValueError('Previously released row missing or changed')
        return {**prior, 'already_applied': True}
    keys = set().union(*(identities(r) for r in existing))
    for r in records:
        newkeys = identities(r['target'])
        if keys & newkeys:
            raise ValueError('Current corpus/release duplicate: ' + r['candidate_id'])
        keys.update(newkeys)
    result = {k:data[k] for k in ('release_id','records_sha256','approval_basis','source_review_commit','assessment_sha256')}
    result.update(records_before=len(existing), records_added=len(records), records_after=len(existing)+len(records),
                  existing_records_modified=0, publication_approved=True,
                  released=[{k:r[k] for k in ('collection','candidate_id','content_sha256','submission')} for r in records])
    if write:
        additions = [r['target'] for r in records]
        fields = list(dict.fromkeys(fields + [k for r in additions for k in r]))
        temp = corpus.with_suffix('.release.tmp')
        with temp.open('w', encoding='utf-8', newline='') as f:
            writer=csv.DictWriter(f, fieldnames=fields); writer.writeheader(); writer.writerows(existing + additions)
        temp.replace(corpus)
        receipt.parent.mkdir(parents=True,exist_ok=True)
        receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--corpus',type=Path,default=Path('data/accepted_classified.csv'))
    p.add_argument('--receipt',type=Path,required=True)
    p.add_argument('--write',action='store_true')
    a=p.parse_args()
    print(json.dumps(apply_release(a.manifest,a.corpus,a.receipt,a.write),indent=2))

"""Apply an explicitly authorized, content-bound APWG release once."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
from alex.pipelines.apwg_import import _doi
from alex.pipelines.apwg_import_recommendation import recommendation
from alex.pipelines.apwg_quality_review import assess
from alex.utils.text import clean, normalize_title


def release_digest(rows: list[dict]) -> str:
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode()).hexdigest()


def apply_release(manifest: Path, corpus: Path, receipt: Path, write: bool = False) -> dict:
    data = json.loads(manifest.read_text())
    rows = data['records']
    if (data.get('publication_approved') is not True or not data.get('approval_basis') or
            len(rows) != data['expected_records'] or release_digest(rows) != data['records_sha256']):
        raise ValueError('Release authorization/content mismatch')
    if len({_doi(r.get('doi')) for r in rows}) != len(rows) or any(not _doi(r.get('doi')) for r in rows):
        raise ValueError('Release DOI identities must be unique and confirmed')
    for row in rows:
        # Recompute quality from the actual release text/counts; editorial
        # approval never defeats a quality or bibliography hold.
        reviewed = {**row, **{k: str(v) for k, v in assess(row).items()}}
        if recommendation(reviewed)[0] != 'editorially_approved_pending_release':
            raise ValueError('Unapproved, changed, duplicate or quality-held release record: '+row['title'])
    if write and os.getenv('APWG_ENABLE_IMPORT') != '1':
        raise RuntimeError('APWG_ENABLE_IMPORT=1 required for authorized corpus write')
    if receipt.exists():
        previous = json.loads(receipt.read_text())
        if (previous.get('release_id') != data['release_id'] or
                previous.get('records_sha256') != data['records_sha256']):
            raise ValueError('Existing release receipt does not match authorization')
        return {**previous, 'already_applied': True}
    with corpus.open(encoding='utf-8', newline='') as f:
        reader = csv.DictReader(f); fields = list(reader.fieldnames); existing = list(reader)
    titles = {normalize_title(r.get('title', '')) for r in existing}
    dois = {_doi(r.get('doi')) for r in existing if _doi(r.get('doi'))}
    additions = []
    for row in rows:
        if _doi(row['doi']) in dois or normalize_title(row['title']) in titles:
            raise ValueError('An authorized addition already exists; reconcile before release: '+row['title'])
        new = {k: row.get(k, '') for k in (
            'title','authors','year','venue','publisher','doi','abstract','citation_count',
            'citation_count_source','citation_snapshot_created_at','citation_snapshot_run',
            'citation_snapshot_artifact','alternate_citation_count','alternate_citation_count_source',
            'apwg_year','publication_year_source','abstract_source')}
        new.update(Category=row['proposed_category'], Investigation_Type=row['proposed_investigation_type'],
                   source_url=row.get('bibliographic_link') or 'https://doi.org/'+row['doi'],
                   collection_source='APWG.org eCrimes Research',
                   collection_url='https://ecrimeresearch.org/ecrime-research-papers',
                   apwg_source_url=row['apwg_paper_url'], retrieved_at=data['approval_date'],
                   discovery_source='APWG curated eCrime proceedings',
                   harvest_source='Verified APWG release '+data['release_id'],
                   inclusion_path='Explicitly approved APWG release',
                   Keywords='', Tags='', OSINT_Source_Types='', Seminal_Flag='FALSE',
                   total_quality_score=row['quality_score'])
        for target, source in [('venue_score','quality_venue_score'),('citation_score','quality_citation_score'),
                               ('relevance_score','quality_relevance_score'),('institution_score','quality_institution_score')]:
            new[target]=row[source]
        additions.append(new)
        titles.add(normalize_title(row['title']));dois.add(_doi(row['doi']))
    result={'release_id':data['release_id'],'records_sha256':data['records_sha256'],
            'source_artifact':data['source_artifact'],'records_before':len(existing),
            'records_added':len(additions),'records_after':len(existing)+len(additions),
            'publication_approved':True,'existing_records_modified':0}
    if write:
        fields = list(dict.fromkeys(fields+[k for row in additions for k in row]))
        temporary=corpus.with_suffix('.release.tmp')
        with temporary.open('w',encoding='utf-8',newline='') as f:
            writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(existing+additions)
        temporary.replace(corpus)
        receipt.parent.mkdir(parents=True,exist_ok=True)
        receipt.write_text(json.dumps(result,indent=2)+'\n')
    return result


def main() -> None:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--corpus',type=Path,default=Path('data/accepted_classified.csv'))
    p.add_argument('--receipt',type=Path,default=Path('data/apwg_release_receipt.json'))
    p.add_argument('--write',action='store_true')
    a=p.parse_args()
    print(json.dumps(apply_release(a.manifest,a.corpus,a.receipt,a.write),indent=2))


if __name__=='__main__':
    main()

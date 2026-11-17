"""A controlled complete lifecycle. Editorial receipts here are synthetic."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from stage1.engine import REQUIRED_CHECKS, Store, digest


def records():
    return [{
        'title':'Synthetic ALEX '+name, 'year':2026, 'doi':'10.0000/alex-fixture-'+name,
        'author':'Synthetic fixture', 'source_url':'https://example.invalid/'+name,
        'publication_date':'2026', 'publication_date_precision':'year',
        'publication_date_source':'fixture', 'collection':'synthetic-stage1',
    } for name in ('approved','rejected','held')]


def provider_responses():
    return {digest(record):{name:{'result':'pass','evidence':'synthetic '+name+' evidence; no live provider'} for name in REQUIRED_CHECKS} for record in records()}


def run(database, preview):
    store = Store(database)
    try:
        ids = [store.discover('controlled-fixture',str(i),record) for i,record in enumerate(records())]
        store.work(provider_responses())
        for candidate_id,record,verdict in zip(ids, records(), ('approve','reject','hold')):
            store.decide(candidate_id,digest(record),verdict,'synthetic-human-reviewer','Explicit fixture decision', 'fixture-review-'+verdict)
        store.work(provider_responses())
        baseline = store.counts()
        for replay in range(3):
            for i,record in enumerate(records()):
                assert store.discover('controlled-fixture',str(i),record) == ids[i]
            assert store.work(provider_responses()) == 0
            assert store.counts() == baseline
        papers = store.export_preview(preview)
        assert len(papers)==1 and papers[0]['id']==ids[0]
        return {'mode':'fixture_only','counts':store.counts(),'preview_ids':[p['id'] for p in papers],
                'three_replays_without_duplicates':True,'rejected_unpublished':True,'held_unpublished':True,
                'live_providers_verified':False,'production_restore_verified':False,'scheduled_execution_verified':False}
    finally:
        store.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--database',required=True)
    parser.add_argument('--preview',required=True)
    parser.add_argument('--evidence',required=True)
    args = parser.parse_args()
    evidence = run(args.database,args.preview)
    Path(args.evidence).write_text(json.dumps(evidence,indent=2)+'\n')
    print(json.dumps(evidence,sort_keys=True))


if __name__ == '__main__':
    main()

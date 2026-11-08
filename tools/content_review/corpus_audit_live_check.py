"""Read-only aggregate reconciliation of receipt-bound corpus audit history.

Private Site rows and candidate identities remain in memory. Matching a key is
not a publication, a deletion authorization, or proof that an item is absent.
"""
from collections import Counter
import json
from pathlib import Path
import sys
import urllib.error
import urllib.request

from tools.content_review.corpus_audit_history import plan
from tools.content_review.site_reconcile_client import NoRedirect, read_snapshot, remote_heads
from tools.content_review.verified_inputs import _path_blob, load_inputs

PUBLIC_URL='https://alex.riseinfosec.org/data/papers.json'
MAX_PUBLIC_BYTES=32*1024*1024


def read_public(*, opener=None):
    request=urllib.request.Request(PUBLIC_URL,headers={'Accept':'application/json','Cache-Control':'no-cache',
                                                       'User-Agent':'ALEX-Publication-Verification'})
    try:
        with (opener or urllib.request.build_opener(NoRedirect)).open(request,timeout=25) as response:
            if response.status!=200:raise ValueError('Public catalogue read failed')
            raw=response.read(MAX_PUBLIC_BYTES+1)
    except (OSError,urllib.error.URLError) as exc:
        raise ValueError('Public catalogue read failed') from exc
    if len(raw)>MAX_PUBLIC_BYTES:raise ValueError('Public catalogue exceeds bound')
    return raw


def _text(value):
    return ' '.join(str(value or '').casefold().split())


def _doi(value):
    value=_text(value)
    for prefix in ('https://doi.org/','http://doi.org/','https://dx.doi.org/','http://dx.doi.org/','doi:'):
        if value.startswith(prefix):return value[len(prefix):].strip()
    return value


def _keys(row):
    doi=_doi(row.get('doi')); urls={_text(row.get(k)) for k in ('source_url','link') if row.get(k)}
    title,year=_text(row.get('title')),_text(row.get('year'))
    return doi,urls,(title,year) if title and year else None


def catalogue_comparison(outcomes, audit_rows, public_records):
    if not isinstance(outcomes,list) or not isinstance(audit_rows,list) or not isinstance(public_records,list):
        raise ValueError('Complete corpus audit inventories required')
    rows={}
    for row in audit_rows:
        if not isinstance(row,dict) or not isinstance(row.get('candidate_id'),str) or row['candidate_id'] in rows:
            raise ValueError('Audit inventory identities are invalid')
        rows[row['candidate_id']]=row
    dois,urls,titles=set(),set(),set()
    for row in public_records:
        if not isinstance(row,dict):raise ValueError('Public catalogue inventory invalid')
        doi,values,title=_keys(row)
        if doi:dois.add(doi)
        urls.update(values)
        if title:titles.add(title)
    result={'historical_removal_receipted':Counter(),'historical_keep_receipted':Counter()}
    for item in outcomes:
        if not isinstance(item,dict):raise ValueError('Audit outcomes invalid')
        kind=item.get('status')
        if kind not in result:continue
        row=rows.get(item.get('candidate_id'))
        if row is None:raise ValueError('Historical candidate unavailable')
        doi,values,title=_keys(row)
        if not doi and not values and title is None:status='no_comparable_key'
        elif (doi and doi in dois) or values.intersection(urls) or (title is not None and title in titles):status='possible_exact_key_match'
        else:status='no_exact_key_match'
        result[kind][status]+=1
    return {key:dict(value) for key,value in result.items()}


def inspect(repo, token, *, heads_reader=remote_heads, snapshot_reader=read_snapshot, inputs_reader=load_inputs,
            history_plan=plan, blob_reader=_path_blob, public_reader=read_public):
    heads=heads_reader(repo);inputs=inputs_reader(repo,heads['review'],heads['main'])
    snapshot,confirmed=snapshot_reader(token)
    history=history_plan(repo,heads['review'],heads['main'],snapshot,confirmed,inputs['reconciliation_manifests'],
                         inputs['public'],observed_heads=heads)
    main_raw,_=blob_reader(repo,heads['main'],'data/papers.json')
    if json.loads(main_raw)!=inputs['public']:raise ValueError('Immutable public inputs differ')
    deployed=public_reader();matches=deployed==main_raw
    comparison=catalogue_comparison(history['outcomes'],inputs['reconciliation_manifests']['corpus-audit']['records'],inputs['public'])
    if heads_reader(repo)!=heads:raise ValueError('A source head changed during corpus audit')
    return {'status':'read_only_corpus_audit','historical_outcomes':history['outcome_counts'],
            'catalogue_key_comparison':comparison,'public_catalogue_matches_main':matches,
            'comparison_note':'Exact key matches are possible matches, not identity or absence proof.',
            'review_head':heads['review'],'main_head':heads['main'],'transactional_snapshot':False,
            'lease_verified':False,'candidate_processing':False,'publication_authorized':False,'writes':0,
            'requires_recheck_under_lease':True}


def main():
    token=sys.stdin.readline().rstrip('\r\n')
    try:result=inspect(Path.cwd(),token)
    except (ValueError,KeyError,TypeError,OSError):
        print(json.dumps({'status':'blocked','reason':'read_only_corpus_audit_failed'}));return 1
    print(json.dumps(result,sort_keys=True));return 0


if __name__=='__main__':raise SystemExit(main())

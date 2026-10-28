"""Apply explicitly authorized, hash-bound corpus removals and approved additions."""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
from pathlib import Path
from alex.editorial_exclusions import load_keys,record_keys,exclusion_keys
from alex.pipelines.content_review_release import apply_release,digest


def public_digest(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def apply(root:Path,manifest:Path,write=False):
    data=json.loads(manifest.read_text())
    removals,keeps=data['removals'],data['keeps']
    if (data.get('publication_approved') is not True or not data.get('approval_basis') or
        digest({'removals':removals,'keeps':keeps})!=data['records_sha256']):
        raise ValueError('Removal/keep authorization or content digest mismatch')
    for rows,decision in ((removals,'rejected'),(keeps,'approved')):
        if any(r['decision']!=decision or not r['submission_id'] or not r['payload_hash'] or not r['reviewed_content_sha256'] for r in rows):
            raise ValueError('Unbound or conflicting human decision')
    identities=[r['candidate_id'] for r in removals+keeps]
    if len(set(identities))!=len(identities):raise ValueError('Repeated or conflicting review identity')
    excluded_path=root/'config/corpus_exclusions.json'
    additions=root/data['addition_manifest']
    for path,expected in ((excluded_path,data['exclusions_sha256']),(additions,data['addition_manifest_sha256'])):
        if hashlib.sha256(path.read_bytes()).hexdigest()!=expected:raise ValueError('Release dependency digest mismatch')
    exclusions=load_keys(excluded_path)
    for r in removals:
        if not record_keys(r)&exclusions:raise ValueError('Removal lacks durable exclusion')
    bundle=json.loads(additions.read_text())
    if any(record_keys(r['target'])&exclusions for r in bundle['records']):raise ValueError('Approved addition conflicts with human exclusion')
    public=root/'data/papers.json';corpus=root/'data/accepted_classified.csv'
    receipt=root/'data/content_review_release_receipts'/f"{data['release_id']}.json"
    with corpus.open(newline='',encoding='utf-8') as f:
        reader=csv.DictReader(f);fields=reader.fieldnames;existing=list(reader)
    if receipt.exists():
        prior=json.loads(receipt.read_text())
        if prior['records_sha256']!=data['records_sha256']:raise ValueError('Receipt does not match release')
        keys=set().union(*(record_keys(r) for r in existing))
        if any(exclusion_keys(r)&keys for r in removals):raise ValueError('Removed identity has reappeared')
        if any(not(record_keys(r)&keys) for r in keeps):raise ValueError('Kept identity is missing')
        apply_release(additions,corpus,root/'data/content_review_release_receipts'/f"{bundle['release_id']}.json",False)
        return {**prior,'already_applied':True}
    raw=public.read_bytes();papers=json.loads(raw)
    if hashlib.sha256(raw).hexdigest()!=data['source_corpus_sha256'] or len(papers)!=data['source_corpus_records'] or len(existing)!=len(papers):
        raise ValueError('Public/canonical corpus changed; reconcile before applying decisions')
    byid={p['id']:p for p in papers};index={p['id']:i for i,p in enumerate(papers)}
    for r in removals+keeps:
        p=byid[r['original_public_id']]
        if public_digest(p)!=r['public_record_sha256']:raise ValueError('Reviewed public content changed')
        row=existing[index[p['id']]]
        if row['title']!=p['title'] or row['abstract']!=p['summary'] or row['authors']!=p['author']:
            raise ValueError('Canonical/public record mismatch')
    removed_ids={r['original_public_id'] for r in removals}
    remaining=[row for p,row in zip(papers,existing) if p['id'] not in removed_ids]
    if any(record_keys(r)&exclusions for r in remaining):raise ValueError('Exclusions would remove an unapproved extra public record')
    result={'release_id':data['release_id'],'records_sha256':data['records_sha256'],
            'records_before':len(existing),'removed':len(removals),'audit_kept':len(keeps),
            'added':len(bundle['records']),'records_after':len(remaining)+len(bundle['records']),
            'retained_metadata_modified':0,'exclusion_records':len(json.loads(excluded_path.read_text())['records']),
            'approval_basis':data['approval_basis'],'removals':removals,'keeps':keeps}
    if result['records_after']!=data['expected_after']:raise ValueError('Unexpected final corpus count')
    if write:
        tmp=corpus.with_suffix('.reviews.tmp')
        with tmp.open('w',newline='',encoding='utf-8') as f:
            writer=csv.DictWriter(f,fieldnames=fields);writer.writeheader();writer.writerows(remaining)
        tmp.replace(corpus)
        added=apply_release(additions,corpus,root/'data/content_review_release_receipts'/f"{bundle['release_id']}.json",True)
        if added['records_after']!=result['records_after']:raise ValueError('Addition result mismatch')
        receipt.parent.mkdir(parents=True,exist_ok=True);receipt.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--root',type=Path,default=Path('.'));p.add_argument('--write',action='store_true');a=p.parse_args()
    result=apply(a.root,a.manifest,a.write)
    print(json.dumps({k:v for k,v in result.items() if k not in ('removals','keeps')},indent=2))

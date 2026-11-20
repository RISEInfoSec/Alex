#!/usr/bin/env python3
"""Read-only comparison of a main queue row and exported staging evidence.

The packet must be obtained separately through the owner-authenticated staging
export. A caller-supplied SHA-256 verifies bytes, not the export's origin.
Nothing is published, approved, sent, or written by this command.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import re
import sqlite3
from pathlib import Path
from alex.editorial_exclusions import load_keys
from alex.metadata_holds import load_holds
from alex.pipelines.source_relevance_reconcile import reconcile
from alex.utils.io import root_file


def snapshot_packet(raw):
    """Verify and restore a chunked staging SQL snapshot in isolated memory."""
    try:
        frames=[json.loads(line) for line in raw.splitlines()]
        if len(frames)<2 or frames[0]['type']!='manifest' or frames[-1]['type']!='end':
            raise ValueError('snapshot_frames_invalid')
        manifest=frames[0]['manifest'];chunks=manifest['chunks']
        if (manifest['format']!='alex-chunked-sql-v1' or len(frames)!=len(chunks)+2 or
                frames[-1]['chunks']!=len(chunks) or frames[-1]['sql_sha256']!=manifest['sql_sha256']):
            raise ValueError('snapshot_frames_invalid')
        parts=[]
        for expected,frame in zip(chunks,frames[1:-1]):
            encoded=frame['data'].encode('utf-8')
            if (frame['type']!='chunk' or frame['index']!=expected['index'] or
                    len(encoded)!=expected['bytes'] or hashlib.sha256(encoded).hexdigest()!=expected['sha256']):
                raise ValueError('snapshot_chunk_invalid')
            parts.append(frame['data'])
        sql=''.join(parts)
        if len(sql.encode('utf-8'))!=manifest['total_bytes'] or hashlib.sha256(sql.encode('utf-8')).hexdigest()!=manifest['sql_sha256']:
            raise ValueError('snapshot_sql_hash_mismatch')
    except (KeyError,TypeError,UnicodeDecodeError,json.JSONDecodeError) as exc:
        raise ValueError('snapshot_frames_invalid') from exc
    db=sqlite3.connect(':memory:')
    try:
        db.execute('PRAGMA temp_store=MEMORY')
        # SQL from an export must not attach files or invoke file/extension
        # functions. Restore only in memory and never create an on-disk DB.
        def authorize(action,arg1,arg2,database,trigger):
            if action in (sqlite3.SQLITE_ATTACH,sqlite3.SQLITE_DETACH):return sqlite3.SQLITE_DENY
            if action==sqlite3.SQLITE_FUNCTION and (arg2 or arg1 or '').lower() in {'load_extension','readfile','writefile'}:
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK
        db.set_authorizer(authorize)
        db.executescript(sql)
        if db.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchall():
            raise ValueError('snapshot_integrity_failed')
        db.row_factory=sqlite3.Row
        return {'reviews':[dict(r) for r in db.execute('SELECT * FROM source_relevance_reviews')],
                'decisions':[dict(r) for r in db.execute('SELECT * FROM source_relevance_decisions')]}
    finally:
        db.close()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('queue','packet','packet-sha256','queue-id','review-id','stage-policy','stage-source-tiers','implementation-hash'):
        p.add_argument('--'+name,required=True)
    a=p.parse_args()
    for value in (a.packet_sha256,a.queue_id,a.review_id,a.implementation_hash):
        if not re.fullmatch('[0-9a-f]{64}',value):raise ValueError('expected_sha256_required')
    raw=Path(a.packet).read_bytes()
    if len(raw)>40*1024*1024 or hashlib.sha256(raw).hexdigest()!=a.packet_sha256:raise ValueError('packet_hash_mismatch')
    try:
        packet=json.loads(raw)
    except json.JSONDecodeError:
        packet=snapshot_packet(raw)
    if not isinstance(packet.get('reviews'),list) or not isinstance(packet.get('decisions'),list):raise ValueError('invalid_packet')
    csv.field_size_limit(100000000)
    with open(a.queue,encoding='utf-8',newline='') as stream:
        rows=[r for r in csv.DictReader(stream) if r.get('source_relevance_review_id')==a.queue_id]
    if len(rows)!=1:raise ValueError('main_review_identity_ambiguous')
    reviews=[r for r in packet['reviews'] if r.get('id')==a.review_id]
    decisions=[r for r in packet['decisions'] if r.get('candidate_id')==a.review_id]
    if len(reviews)>1 or len(decisions)>1:raise ValueError('staging_review_identity_ambiguous')
    if not reviews:
        if decisions:raise ValueError('decision_without_review')
        result={'status':'pending_staging_review','publication_approved':False,'editorial_approved':False,
                'classification_approved':False,'main_review_id':a.queue_id,'staging_review_id':a.review_id}
    else:
        tiers=json.loads(root_file('config','source_tiers.json').read_text())
        policy={'weights':json.loads(root_file('config','quality_weights.json').read_text()),
                'registry':json.loads(root_file('config','query_registry.json').read_text()),
                'venues':json.loads(root_file('config','venue_whitelist.json').read_text())['high_trust']}
        result=reconcile(rows[0],reviews[0],decisions[0] if decisions else None,policy=policy,tiers=tiers,
                         site_policy=json.loads(Path(a.stage_policy).read_text()),
                         site_tiers=json.loads(Path(a.stage_source_tiers).read_text()),
                         implementation_hash=a.implementation_hash,
                         exclusions=load_keys(root_file('config','corpus_exclusions.json')),
                         metadata_holds={v['doi'] for v in load_holds(root_file('config','corpus_metadata_holds.json'))})
    result.update(packet_sha256=a.packet_sha256,export_origin_verified_by_command=False)
    print(json.dumps(result,indent=2,ensure_ascii=False))

if __name__=='__main__':
    main()

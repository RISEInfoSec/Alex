import json
from copy import deepcopy
import pytest
from alex.editorial_exclusions import record_keys
from alex.pipelines.apwg_quality_review import assess
from alex.pipelines.rescore import _relevance_policy_hash, _relevance_review_id
from alex.pipelines.source_relevance_reconcile import _digest, _json, reconcile
from alex.source_tiers import source_designation
from alex.utils.io import root_file

@pytest.fixture
def evidence():
    weights=json.loads(root_file('config','quality_weights.json').read_text())
    registry=json.loads(root_file('config','query_registry.json').read_text())
    venues=json.loads(root_file('config','venue_whitelist.json').read_text())['high_trust']
    tiers=json.loads(root_file('config','source_tiers.json').read_text())
    policy={'weights':weights,'registry':registry,'venues':venues}
    site_policy={**policy,'python_reference_policy_hash':'a'*64,'excluded_keys':[],'metadata_holds':[]}
    record={'title':'Payment Card Web Skimming','authors':'A Researcher','year':2025,'doi':'',
            'source_url':'https://ecrimeresearch.org/paper','abstract':'A study of payment card information used at online stores.',
            'venue':'eCrime','citation_count':0}
    q=assess(record,(weights,registry,venues));assert q['quality_core_term_gate']=='fail'
    candidate_id=_digest(record)
    checks={}
    for name in ('metadata','access','format','relevance','quality'):
        ev={'candidate_content_hash':candidate_id,'policy_hash':'a'*64,'hosted_implementation_hash':'b'*64}
        if name=='quality':ev['assessment']=q
        checks[name]={'result':'hold' if name in ('relevance','quality') else 'pass','evidence':_json(ev)}
    source=source_designation(record);provenance={**source,'evidence_url':record['source_url']}
    review_id=_digest({'id':candidate_id,'checks':checks,'source':provenance,'independentHold':'required_check_held'})
    review={'id':review_id,'candidate_id':candidate_id,'record':_json(record),'checks':_json(checks),
            'source':source['source'],'tier':source['tier'],'source_evidence':_json(provenance),
            'independent_hold':'required_check_held','evidence_hash':review_id}
    decision={'candidate_id':review_id,'evidence_hash':review_id,'verdict':'approve',
              'reason':'Relevant payment investigation','actor':'local-test-owner','decided_at':'2026-11-20T00:00:00Z'}
    row={**record,'venue_score':q['quality_venue_score'],'citation_score':q['quality_citation_score'],
         'institution_score':q['quality_institution_score'],'institution_bonus':q['quality_institution_bonus'],
         'title_anchor_bonus':q['quality_title_bonus'],'relevance_score':q['quality_relevance_score'],
         'total_quality_score':q['quality_score']}
    minimum=1
    hits=[x for x in registry['core_keywords'] if x.lower() in (record['title']+' '+record['abstract']).lower()]
    reasons=[f'Core term matches {len(hits)} below required {minimum}; matches: {", ".join(hits) or "none"}']
    if q['quality_relevance_score']<float(weights['relevance_floor']):
        reasons.append(f'Relevance score {float(q["quality_relevance_score"])} below floor {float(weights["relevance_floor"])}')
    ph=_relevance_policy_hash(registry,weights,venues,tiers['tiers'])
    rid=_relevance_review_id(row,source,minimum,reasons,ph)
    row.update(source_relevance_review_id=rid,source_tier=source['tier'],source_tier_name=source['source'],
               source_review_priority=str(source['priority']),scoring_policy_sha256=ph,review_reason='; '.join(reasons),
               recommended_action='human review')
    return {'row':row,'review':review,'decision':decision,'policy':policy,'tiers':tiers,
            'site_policy':site_policy,'site_tiers':deepcopy(tiers)}

def run(e):
    return reconcile(e['row'],e['review'],e['decision'],policy=e['policy'],tiers=e['tiers'],
                     site_policy=e['site_policy'],site_tiers=e['site_tiers'],implementation_hash='b'*64,
                     exclusions=e.get('exclusions',frozenset()))

def test_matching_relevance_decision_creates_only_unapproved_draft(evidence):
    before=deepcopy(evidence)
    out=run(evidence)
    assert out['status']=='reconciliation_draft' and out['relevance_verdict']=='approve'
    assert not out['publication_approved'] and not out['editorial_approved'] and not out['classification_approved']
    assert 'records' not in out and 'target' not in out
    assert evidence==before

def test_no_staging_decision_is_pending_not_approved(evidence):
    evidence['decision']=None
    out=run(evidence)
    assert out['status']=='pending_relevance_decision' and out['relevance_verdict']=='pending'
    assert not out['publication_approved']

@pytest.mark.parametrize('mutation', ['source','content','whitespace','stage_policy','main_policy','score','reason','decision','exclusion','tier_registry'])
def test_fails_closed_on_drift_or_existing_human_exclusion(evidence,mutation):
    e=deepcopy(evidence)
    if mutation=='source': e['row']['source_tier_name']='SANS'
    elif mutation=='content': e['row']['abstract']+=' changed'
    elif mutation=='whitespace': e['row']['abstract']=e['row']['abstract'].replace('payment card','payment  card')
    elif mutation=='stage_policy': e['site_policy']['weights']['relevance_floor']=9
    elif mutation=='main_policy': e['row']['scoring_policy_sha256']='0'*64
    elif mutation=='score': e['row']['total_quality_score']=0
    elif mutation=='reason': e['row']['review_reason']='different'
    elif mutation=='decision': e['decision']['evidence_hash']='0'*64
    elif mutation=='exclusion':
        e['exclusions']=record_keys(e['row'])
        e['site_policy']['excluded_keys']=sorted(e['exclusions'])
    elif mutation=='tier_registry': e['site_tiers']['tiers']['trusted_curated']['priority']=9
    with pytest.raises(ValueError):run(e)


def test_rehashed_unverified_source_provenance_is_refused(evidence):
    e=deepcopy(evidence)
    source=json.loads(e['review']['source_evidence'])
    source['evidence_url']='https://attacker.invalid/forged'
    checks=json.loads(e['review']['checks'])
    evidence_hash=_digest({'id':e['review']['candidate_id'], 'checks':checks, 'source':source,
                           'independentHold':e['review']['independent_hold']})
    e['review'].update(id=evidence_hash,evidence_hash=evidence_hash,source_evidence=_json(source))
    e['decision'].update(candidate_id=evidence_hash,evidence_hash=evidence_hash)
    with pytest.raises(ValueError,match='staging_source_provenance_mismatch'):run(e)

def test_cli_emits_only_unapproved_draft_and_never_writes_inputs(tmp_path,monkeypatch,capsys,evidence):
    import csv,hashlib,sys
    from scripts import reconcile_source_relevance as cli
    from alex.editorial_exclusions import load_keys
    from alex.metadata_holds import load_holds
    root=__import__('alex.utils.io',fromlist=['root_file']).root_file
    e=deepcopy(evidence)
    e['site_policy']['excluded_keys']=sorted(load_keys(root('config','corpus_exclusions.json')))
    e['site_policy']['metadata_holds']=sorted(x['doi'] for x in load_holds(root('config','corpus_metadata_holds.json')))
    queue=tmp_path/'queue.csv';packet=tmp_path/'packet.json';site_policy=tmp_path/'policy.json';site_tiers=tmp_path/'tiers.json'
    with queue.open('w',newline='',encoding='utf-8') as f:
        w=csv.DictWriter(f,fieldnames=list(e['row']));w.writeheader();w.writerow(e['row'])
    packet.write_text(json.dumps({'reviews':[e['review']],'decisions':[e['decision']]}))
    site_policy.write_text(json.dumps(e['site_policy']));site_tiers.write_text(json.dumps(e['site_tiers']))
    files=[queue,packet,site_policy,site_tiers];before=[p.read_bytes() for p in files]
    packet_hash=hashlib.sha256(packet.read_bytes()).hexdigest()
    args=['reconcile','--queue',str(queue),'--packet',str(packet),'--packet-sha256',packet_hash,
          '--queue-id',e['row']['source_relevance_review_id'],'--review-id',e['review']['id'],
          '--stage-policy',str(site_policy),'--stage-source-tiers',str(site_tiers),'--implementation-hash','b'*64]
    monkeypatch.setattr(sys,'argv',args)
    cli.main();out=json.loads(capsys.readouterr().out)
    assert out['status']=='reconciliation_draft' and not out['publication_approved']
    assert not out['export_origin_verified_by_command']
    assert before==[p.read_bytes() for p in files]
    args[args.index('--packet-sha256')+1]='0'*64
    with pytest.raises(ValueError,match='packet_hash_mismatch'):cli.main()

def test_nested_provenance_requires_strict_json_and_exact_canonical_value(evidence):
    e=deepcopy(evidence)
    record=json.loads(e['review']['record']);record['source_checkpoint_artifacts']={'config/example.json':'a'*64}
    candidate=_digest(record)
    checks=json.loads(e['review']['checks'])
    for check in checks.values():
        ev=json.loads(check['evidence']);ev['candidate_content_hash']=candidate;check['evidence']=_json(ev)
    source=json.loads(e['review']['source_evidence'])
    rid=_digest({'id':candidate,'checks':checks,'source':source,'independentHold':e['review']['independent_hold']})
    e['review'].update(id=rid,candidate_id=candidate,evidence_hash=rid,record=_json(record),checks=_json(checks))
    e['decision'].update(candidate_id=rid,evidence_hash=rid)
    e['row']['source_checkpoint_artifacts']='{ "config/example.json": "'+'a'*64+'" }'
    source_main=source_designation(e['row'])
    # The generated queue hashes its complete CSV source field exactly.
    text=e['row']['review_reason'];reason_parts=[text]
    if '; Relevance score ' in text:
        first,second=text.split('; Relevance score ',1);reason_parts=[first,'Relevance score '+second]
    e['row']['source_relevance_review_id']=_relevance_review_id(e['row'],source_main,1,reason_parts,e['row']['scoring_policy_sha256'])
    assert run(e)['status']=='reconciliation_draft'
    e['row']['source_checkpoint_artifacts']='{"config/example.json": "'+'b'*64+'"}'
    with pytest.raises(ValueError,match='candidate_content_mismatch'):run(e)
    e['row']['source_checkpoint_artifacts']="{'verified': True}"
    with pytest.raises(ValueError,match='candidate_content_mismatch'):run(e)

def test_chunked_snapshot_restore_is_read_only_memory_and_checks_chunks(tmp_path):
    import hashlib,sqlite3
    from scripts.reconcile_source_relevance import snapshot_packet
    def packet(sql):
        data=sql.encode();h=hashlib.sha256(data).hexdigest()
        chunk={'index':0,'bytes':len(data),'sha256':h}
        return ('\n'.join(json.dumps(x) for x in [
            {'type':'manifest','manifest':{'format':'alex-chunked-sql-v1','chunks':[chunk],
                'total_bytes':len(data),'sql_sha256':h}},
            {'type':'chunk','index':0,'data':sql},
            {'type':'end','chunks':1,'sql_sha256':h}])+'\n').encode()
    sql="CREATE TABLE source_relevance_reviews(id TEXT); CREATE TABLE source_relevance_decisions(candidate_id TEXT); INSERT INTO source_relevance_reviews VALUES ('hello');"
    out=snapshot_packet(packet(sql));assert out=={'reviews':[{'id':'hello'}],'decisions':[]}
    frames=[json.loads(x) for x in packet(sql).splitlines()];frames[1]['data']+=' '
    with pytest.raises(ValueError,match='snapshot_chunk_invalid'):snapshot_packet(('\n'.join(json.dumps(x) for x in frames)+'\n').encode())
    target=tmp_path/'must-not-exist.db'
    with pytest.raises(sqlite3.DatabaseError):snapshot_packet(packet(f"ATTACH DATABASE '{target}' AS forbidden;"))
    assert not target.exists()

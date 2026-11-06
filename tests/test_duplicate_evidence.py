from tools.content_review.duplicate_evidence import upstream_alias,audit

def test_same_arxiv_discovery_alias_is_not_second_work():
    a=dict(candidate_id='a',title='Human & Security',authors='A; B',source_url='https://arxiv.org/abs/2606.10083')
    b=dict(candidate_id='b',title='Human &amp; Security',authors='A; B',doi='10.48550/arxiv.2606.10083')
    assert upstream_alias(a,b)
    assert audit(a,{},[b],set())['status']=='passed'
    # An already prepared/published second record still needs explicit reconciliation.
    assert audit(a,{'public':[b]},[],set())['status']=='held'
    b['authors']='Someone else';assert not upstream_alias(a,b)

def test_same_candidate_id_in_another_collection_is_not_skipped():
    row=dict(candidate_id='same',title='Matching work',authors='A',year=2026)
    assert audit(row,{'weekly':[dict(row)]},[],set(),source_collection='weekly')['status']=='passed'
    assert audit(row,{'public':[dict(row)]},[],set(),source_collection='weekly')['status']=='held'
    assert audit(row,{'weekly':[dict(row)]},[],set())['status']=='held'

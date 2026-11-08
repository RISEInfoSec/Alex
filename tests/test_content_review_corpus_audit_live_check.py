from copy import deepcopy
import io
import json

import pytest

from tools.content_review.corpus_audit_live_check import PUBLIC_URL, catalogue_comparison, inspect, read_public


def sample():
    rows=[{'candidate_id':'private-a','doi':'https://doi.org/10.1/Example','title':'Old','year':2020},
          {'candidate_id':'private-b','source_url':'https://example.test/paper','title':'New','year':2021},
          {'candidate_id':'private-c'}]
    outcomes=[{'candidate_id':'private-a','status':'historical_removal_receipted'},
              {'candidate_id':'private-b','status':'historical_keep_receipted'},
              {'candidate_id':'private-c','status':'historical_keep_receipted'}]
    public=[{'doi':'10.1/example','title':'A different title','year':2024},
            {'source_url':'https://example.test/paper','title':'New','year':2021}]
    return rows,outcomes,public


def test_comparison_is_conservative_and_reports_aggregates_only():
    rows,outcomes,public=sample();before=deepcopy((rows,outcomes,public))
    value=catalogue_comparison(outcomes,rows,public)
    assert value=={'historical_removal_receipted':{'possible_exact_key_match':1},
                   'historical_keep_receipted':{'possible_exact_key_match':1,'no_comparable_key':1}}
    assert 'private-' not in json.dumps(value) and (rows,outcomes,public)==before
    with pytest.raises(ValueError,match='identities'):
        catalogue_comparison(outcomes,rows+[deepcopy(rows[0])],public)


def test_inspection_pins_heads_compares_deployed_bytes_and_never_claims_processing():
    rows,outcomes,public=sample();raw=json.dumps(public).encode();heads={'review':'a'*40,'main':'b'*40}
    inputs={'reconciliation_manifests':{'corpus-audit':{'records':rows}},'public':public}
    history={'outcomes':outcomes,'outcome_counts':{'historical_removal_receipted':1,'historical_keep_receipted':2}}
    kwargs={'heads_reader':lambda _:heads,'snapshot_reader':lambda _:( {'private':'data'}, {'private':'data'} ),
            'inputs_reader':lambda *a:inputs,'history_plan':lambda *a,**k:history,
            'blob_reader':lambda *a:(raw,{}),'public_reader':lambda:raw}
    result=inspect('.','secret',**kwargs)
    assert result['public_catalogue_matches_main'] is True and result['writes']==0
    assert result['candidate_processing'] is False and result['publication_authorized'] is False
    assert result['lease_verified'] is False and 'secret' not in json.dumps(result) and 'private-a' not in json.dumps(result)
    kwargs['public_reader']=lambda:b'[]'
    assert inspect('.','secret',**kwargs)['public_catalogue_matches_main'] is False
    calls=iter([heads,{'review':'c'*40,'main':'b'*40}]);kwargs['heads_reader']=lambda _:next(calls)
    with pytest.raises(ValueError,match='head changed'):inspect('.','secret',**kwargs)


def test_public_reader_uses_fixed_url_without_credentials_and_enforces_size(monkeypatch):
    class Response(io.BytesIO):status=200
    class Opener:
        def open(self,request,timeout):
            assert request.full_url==PUBLIC_URL and timeout==25 and request.get_header('Authorization') is None
            return Response(b'[]')
    assert read_public(opener=Opener())==b'[]'
    monkeypatch.setattr('tools.content_review.corpus_audit_live_check.MAX_PUBLIC_BYTES',1)
    with pytest.raises(ValueError,match='exceeds bound'):
        read_public(opener=Opener())

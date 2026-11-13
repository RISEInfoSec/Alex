from copy import deepcopy
import io
import json

import pytest

from tools.content_review.site_reconcile_client import SITE_URL, inspect, read_snapshot


def snapshot():
    result = {'submissions': [], 'decisions': [], 'jobs': []}
    result['read_evidence'] = {key: {'complete': True, 'rows_received': 0,
        'truncated_values': 0, 'omitted_columns': 0} for key in ('submissions', 'decisions', 'jobs')}
    return result


def test_read_only_inspection_rechecks_heads_and_reports_no_processing():
    heads = {'review': 'a' * 40, 'main': 'b' * 40}
    data = snapshot()
    result = inspect('.', 'private-token', heads_reader=lambda _: heads,
        snapshot_reader=lambda _: (data, deepcopy(data)),
        inputs_reader=lambda *args: {'reconciliation_manifests': {'weekly': {'records': []}}})
    assert result['counts']['decisions'] == 0
    assert result['lease_verified'] is False and result['candidate_processing'] is False
    assert result['requires_recheck_under_lease'] is True
    assert 'private-token' not in json.dumps(result)


def test_changed_remote_head_or_changed_d1_snapshot_fails_closed():
    heads = {'review': 'a' * 40, 'main': 'b' * 40}
    changed = {'review': 'c' * 40, 'main': 'b' * 40}
    data = snapshot()
    calls = iter([heads, changed])
    with pytest.raises(ValueError, match='source head changed'):
        inspect('.', 'token', heads_reader=lambda _: next(calls),
            snapshot_reader=lambda _: (data, deepcopy(data)),
            inputs_reader=lambda *args: {'reconciliation_manifests': {}})
    invalid = deepcopy(data)
    invalid['read_evidence']['jobs']['complete'] = False
    with pytest.raises(ValueError, match='Incomplete jobs'):
        inspect('.', 'token', heads_reader=lambda _: heads,
            snapshot_reader=lambda _: (data, invalid),
            inputs_reader=lambda *args: {'reconciliation_manifests': {}})


def test_private_snapshot_request_has_fixed_destination_and_requires_no_store():
    data = snapshot()
    payload = {'status': 'complete_read_only', 'snapshot': data, 'confirmed_snapshot': data,
        'transactional_snapshot': False, 'lease_verified': False, 'candidate_processing': False}
    class Response(io.BytesIO):
        status = 200
        headers = {'Cache-Control': 'private, no-store'}
    class Opener:
        def open(self, request, timeout):
            assert request.full_url == SITE_URL and timeout == 90
            assert request.get_header('Oai-sites-authorization') == 'Bearer private-token'
            return Response(json.dumps(payload).encode())
    first, second = read_snapshot('private-token', opener=Opener())
    assert first == second == data
    with pytest.raises(ValueError, match='service access'):
        read_snapshot('bad\ntoken', opener=Opener())

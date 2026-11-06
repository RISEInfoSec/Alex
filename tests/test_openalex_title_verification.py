import json
from unittest.mock import MagicMock
import pytest
from scripts import verify_openalex_titles as diagnostic


@pytest.mark.parametrize('failure', [False, True])
def test_diagnostic_bounds_and_stops_on_first_error(tmp_path, monkeypatch, failure):
    monkeypatch.chdir(tmp_path)
    client = MagicMock(events=[])
    monkeypatch.setattr(diagnostic, 'Probe', lambda: client)
    calls = []
    def search(c, title, *args, **kwargs):
        calls.append(title)
        assert kwargs['literal_title'] is True
        c.events.append({'http_status': 400 if failure else 200})
        return [] if failure else [{'id': 'https://openalex.org/W1', 'title': title}]
    monkeypatch.setattr(diagnostic.openalex, 'search', search)
    assert diagnostic.main() == (1 if failure else 0)
    assert len(calls) == (1 if failure else 3)
    receipt = json.loads((tmp_path / '.cache/openalex-title-verification.json').read_text())
    assert receipt['status'] == ('blocked' if failure else 'complete')


def test_diagnostic_no_send_after_its_cap(monkeypatch, tmp_path):
    from alex.utils import http
    monkeypatch.setattr(http, 'CACHE', tmp_path / 'cache.json')
    client = diagnostic.Probe()
    client.events = [{}, {}, {}]
    with pytest.raises(RuntimeError, match='limit'):
        client._send_request('https://api.openalex.org/works')

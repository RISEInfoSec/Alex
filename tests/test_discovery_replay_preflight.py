import hashlib
import json

import pandas as pd
import pytest

from alex.connectors.openalex import OPENALEX
from alex.pipelines import discovery_replay_preflight as preflight
from alex.utils.text import normalize_title


@pytest.fixture
def saved_window(tmp_path, monkeypatch):
    state, head = 'a' * 40, 'b' * 40
    (tmp_path / '.git').mkdir()
    (tmp_path / '.git/alex-state-base').write_text(state)
    (tmp_path / 'data').mkdir()
    def git(args, **kwargs):
        return '.git\n' if args[-1] == '--git-dir' else head + '\n'
    monkeypatch.setattr(preflight.subprocess, 'check_output', git)
    mailto = 'private-mail-context@example.invalid'
    def key(doi, address=mailto):
        url = f'{OPENALEX}/https://doi.org/{doi}'
        return hashlib.sha256(json.dumps(['get_json', url, {'mailto': address}],
                                          sort_keys=True).encode()).hexdigest()
    pd.DataFrame([
        {'title': 'Saved first', 'doi': '10.1/one', 'abstract': ''},
        {'title': 'Saved second', 'doi': '10.1/two', 'abstract': ''},
        {'title': 'Saved third', 'doi': '10.1/three', 'abstract': ''},
        {'title': 'Outside window', 'doi': '10.1/four', 'abstract': ''},
    ]).to_csv(tmp_path / 'data/discovery_candidates.csv', index=False)
    data = {'status': 'partial', 'candidate_titles': [normalize_title('Saved ' + n)
             for n in ('first', 'second', 'third')],
            'responses': {key('10.1/one'): {'ids': {'doi': 'https://doi.org/10.1/one'}},
                          key('10.1/two'): None,
                          key('10.1/four'): {'ids': {'doi': 'https://doi.org/10.1/four'}}}}
    (tmp_path / 'data/discovery_checkpoint.json').write_text(json.dumps(data))
    return tmp_path, state, head, mailto, key, data


def test_exact_positive_and_404_hits_within_saved_window(saved_window):
    root, state, head, mailto, _, _ = saved_window
    assert preflight.verify(root, expected_state=state, expected_checkout=head,
                            minimum_hits='2', mailto=mailto) == (2, 3)


def test_changed_or_missing_mail_context_fails_before_provider_work(saved_window):
    root, state, head, _, _, _ = saved_window
    for mailto in ('different@example.invalid', ''):
        with pytest.raises(ValueError):
            preflight.verify(root, expected_state=state, expected_checkout=head,
                             minimum_hits='2', mailto=mailto)


def test_wrong_state_or_checkout_fails_before_reading_checkpoint(saved_window):
    root, state, head, mailto, _, _ = saved_window
    (root / 'data/discovery_checkpoint.json').unlink()
    for pinned, checkout in (('c' * 40, head), (state, 'd' * 40)):
        with pytest.raises(ValueError, match='preflight_ref_mismatch'):
            preflight.verify(root, expected_state=pinned, expected_checkout=checkout,
                             minimum_hits='2', mailto=mailto)


def test_mismatched_work_identity_is_not_counted(saved_window):
    root, state, head, mailto, key, data = saved_window
    data['responses'][key('10.1/one')] = {'ids': {'doi': 'https://doi.org/10.1/wrong'}}
    (root / 'data/discovery_checkpoint.json').write_text(json.dumps(data))
    with pytest.raises(ValueError, match='checkpoint_cache_context_mismatch'):
        preflight.verify(root, expected_state=state, expected_checkout=head,
                         minimum_hits='2', mailto=mailto)


def test_extra_negative_key_cannot_be_hidden_by_aggregate_hit_count(saved_window):
    root, state, head, mailto, key, data = saved_window
    data['responses'][key('10.1/three')] = {'ids': {'doi': 'https://doi.org/10.1/three'}}
    data['responses']['unmatched-previous-negative'] = None
    (root / 'data/discovery_checkpoint.json').write_text(json.dumps(data))
    with pytest.raises(ValueError, match='checkpoint_cache_context_mismatch'):
        preflight.verify(root, expected_state=state, expected_checkout=head,
                         minimum_hits='2', mailto=mailto)


def test_cli_does_not_print_mail_context_on_failure(saved_window, monkeypatch, capsys):
    root, state, head, mailto, _, _ = saved_window
    monkeypatch.chdir(root)
    monkeypatch.setenv('EXPECTED_PIPELINE_STATE', state)
    monkeypatch.setenv('GITHUB_SHA', head)
    monkeypatch.setenv('MINIMUM_CHECKPOINT_CACHE_HITS', '3')
    monkeypatch.setenv('HARVEST_MAILTO', mailto)
    assert preflight.main() == 1
    out = capsys.readouterr()
    assert mailto not in out.out + out.err
    assert 'checkpoint_cache_context_mismatch' in out.err

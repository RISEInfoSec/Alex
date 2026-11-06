"""Execute the actual workflow diagnostic with retained/malformed responses."""
import json
from pathlib import Path
from textwrap import dedent
from unittest.mock import Mock

import pytest
from alex.pipelines.classify import OpenAIClassificationError


def smoke(monkeypatch, classification, **envelope):
    workflow = (Path(__file__).parents[1] / '.github/workflows/openai_smoketest.yml').read_text()
    code = dedent(workflow.split("python - <<'PY'\n", 1)[1].rsplit('\n          PY', 1)[0])
    monkeypatch.setenv('OPENAI_API_KEY', 'test-only-no-network')
    response = Mock(status_code=200)
    response.json.return_value = {'output_text': json.dumps(classification),
                                  'usage': {'total_tokens': 438},
                                  'status': 'completed', 'id': 'resp_synthetic_fixture', **envelope}
    post = Mock(return_value=response)
    monkeypatch.setattr('requests.post', post)
    exec(compile(code, 'openai_smoketest.yml', 'exec'), {})
    post.assert_called_once()


def test_retained_classification_in_valid_fixture_envelope_passes_workflow(monkeypatch):
    # Exact classification from native run42165017138: HTTP200,438 tokens.
    # The old diagnostic incorrectly required retired Keywords/Tags fields.
    # Status/response ID are synthetic fixture metadata: the historical log
    # retained classification text and usage, not the full response envelope.
    smoke(monkeypatch, {
        'Category': 'Cyber Threat Intelligence', 'Investigation_Type': 'Attribution',
        'OSINT_Source_Types': ['Public Records', 'News Media',
                              'Forums & Communities', 'Leaked Data']})


@pytest.mark.parametrize('extra', [{'Tags': []}, {'OSINT_Source_Types': ['Invented']}])
def test_workflow_rejects_schema_drift(monkeypatch, extra):
    classification = {'Category': 'Cyber Threat Intelligence',
                      'Investigation_Type': 'Attribution', 'OSINT_Source_Types': []}
    with pytest.raises(OpenAIClassificationError):
        smoke(monkeypatch, {**classification, **extra})


@pytest.mark.parametrize('envelope', [{'status': 'incomplete'}, {'id': None}])
def test_workflow_rejects_incomplete_or_unidentified_response(monkeypatch, envelope):
    with pytest.raises(OpenAIClassificationError):
        smoke(monkeypatch, {'Category': 'Other', 'Investigation_Type': 'Other',
                            'OSINT_Source_Types': []}, **envelope)

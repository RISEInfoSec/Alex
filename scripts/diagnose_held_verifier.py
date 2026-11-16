"""Read-only hosted-runner diagnostic, not a production authorization gate.

Use the same fixed-origin held verifier as the local candidate. Fetch four
immutable Git blob byte streams to a private temporary directory so the full
verifier can check their identities, then discard them. No provider calls,
state pushes, publication, deployment or repository writes are performed.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import tempfile
import urllib.error
import urllib.parse

from scripts.legacy_github_provenance_candidate import EvidenceUnavailable, GitHubReadOnly, STATES, _verify


class ObservedOpener:
    """Observe categories only; never emit URLs, headers or exception text."""
    def __init__(self, inner):
        self.inner = inner
        self.events = []

    def open(self, request, timeout=None):
        parsed = urllib.parse.urlsplit(request.full_url)
        path = parsed.path
        if parsed.hostname == 'api.github.com':
            if '/git/blobs/' in path:
                stage = 'blob_download'
            elif '/actions/runs/' in path:
                stage = 'run_metadata'
            elif '/actions/jobs/' in path and path.endswith('/logs'):
                stage = 'job_log_redirect'
            elif '/actions/jobs/' in path:
                stage = 'job_metadata'
            elif '/git/commits/' in path:
                stage = 'git_commit'
            elif '/git/trees/' in path:
                stage = 'git_tree'
            else:
                stage = 'other_github'
        else:
            stage = 'signed_log_storage'
        try:
            response = self.inner.open(request, timeout=timeout)
            status = response.status if response.status in (200, 302, 401, 403, 404, 429) else 'other_http'
            self.events.append({'stage': stage, 'outcome': status})
            return response
        except urllib.error.HTTPError as error:
            status = error.code if error.code in (200, 302, 401, 403, 404, 429) else 'other_http'
            self.events.append({'stage': stage, 'outcome': status})
            raise
        except Exception:
            self.events.append({'stage': stage, 'outcome': 'transport_error'})
            raise


EVIDENCE_ERRORS = {
    'GitHub metadata unavailable': 'github_metadata_unavailable',
    'GitHub job log unavailable': 'github_job_log_unavailable',
    'historical run metadata mismatch': 'run_metadata_mismatch',
    'historical job metadata mismatch': 'job_metadata_mismatch',
    'historical job steps unavailable': 'job_steps_unavailable',
    'historical job step mismatch': 'job_step_mismatch',
    'historical job log hash mismatch': 'job_log_hash_mismatch',
    'historical job log transition mismatch': 'job_log_transition_mismatch',
    'historical citation failure count mismatch': 'citation_failure_count_mismatch',
    'historical commit or tree mismatch': 'git_commit_tree_mismatch',
    'historical tree unavailable': 'git_tree_unavailable',
    'historical candidate blob mismatch': 'candidate_blob_mismatch',
    'local historical blob mismatch': 'local_blob_mismatch',
}


def _fetch_blob(reader: GitHubReadOnly, blob: str, destination: Path) -> None:
    request = reader._request('/git/blobs/' + blob)
    request.add_header('Accept', 'application/vnd.github.raw+json')
    count = 0
    with reader._opener.open(request, timeout=60) as response:
        if response.status != 200 or response.headers.get_content_type() != 'application/octet-stream':
            raise ValueError('blob unavailable')
        with destination.open('xb') as out:
            os.chmod(destination, 0o600)
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                count += len(chunk)
                if count > 64 * 1024 * 1024:
                    raise ValueError('blob too large')
                out.write(chunk)
    if count == 0:
        raise ValueError('empty blob')


def main() -> int:
    observer = None
    try:
        reader = GitHubReadOnly(os.environ.get('GITHUB_TOKEN', ''))
        observer = ObservedOpener(reader._opener)
        reader._opener = observer
        with tempfile.TemporaryDirectory(prefix='alex-held-verifier-') as directory:
            base = Path(directory)
            for _, _, blob, _, filename in STATES:
                _fetch_blob(reader, blob, base / filename)
            result = _verify(reader, base)
        result['diagnostic_events'] = observer.events
        print(json.dumps(result, sort_keys=True))
        if (result.get('status') != 'historical_outputs_verified_held'
                or result.get('citation_http_400_count') != 3
                or any(result.get(key) is not False for key in (
                    'citation_complete', 'publication_authorized', 'provider_access_authorized',
                    'global_fence_verified', 'pending_partition_verified'))):
            return 1
        return 0
    except Exception as error:
        # EvidenceUnavailable messages are converted to an explicit whitelist;
        # all other exceptions, URLs, headers and response bodies stay private.
        reason = EVIDENCE_ERRORS.get(str(error), 'other_validation_failure') if isinstance(error, EvidenceUnavailable) else 'other_failure'
        print(json.dumps({'status': 'diagnostic_unavailable', 'reason': reason,
                          'diagnostic_events': observer.events if observer else [],
                          'citation_complete': False, 'publication_authorized': False,
                          'provider_access_authorized': False, 'global_fence_verified': False,
                          'pending_partition_verified': False}, sort_keys=True))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

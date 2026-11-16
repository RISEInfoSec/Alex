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

from scripts.legacy_github_provenance_candidate import GitHubReadOnly, STATES, verify_held_legacy_provenance


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
    try:
        reader = GitHubReadOnly(os.environ.get('GITHUB_TOKEN', ''))
        with tempfile.TemporaryDirectory(prefix='alex-held-verifier-') as directory:
            base = Path(directory)
            for _, _, blob, _, filename in STATES:
                _fetch_blob(reader, blob, base / filename)
            result = verify_held_legacy_provenance(base)
        print(json.dumps(result, sort_keys=True))
        if (result.get('status') != 'historical_outputs_verified_held'
                or result.get('citation_http_400_count') != 3
                or any(result.get(key) is not False for key in (
                    'citation_complete', 'publication_authorized', 'provider_access_authorized',
                    'global_fence_verified', 'pending_partition_verified'))):
            return 1
        return 0
    except Exception:
        # Never emit a credential, signed URL, response body, or provider data.
        print(json.dumps({'status': 'diagnostic_unavailable', 'provider_access_authorized': False}))
        return 1


if __name__ == '__main__':
    raise SystemExit(main())

"""Verify exact, previously approved PDF bytes before the release executor writes."""
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import requests


def validate_sources(manifest, get=requests.get):
    proof = []
    origins = {}
    for row in manifest['records']:
        source = row['source_revalidation']
        url = source['url']
        parsed = urlsplit(url)
        if parsed.scheme != 'https' or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('Invalid approved source URL')
        time.sleep(max(0, 2 - (time.monotonic() - origins.get(parsed.netloc, 0))))
        try:
            response = get(url, timeout=20, allow_redirects=False,
                           headers={'User-Agent': 'ALEX-ContentReview/1.0 (+https://github.com/RISEInfoSec/Alex)'})
        finally:
            origins[parsed.netloc] = time.monotonic()
        response.raise_for_status()
        body = response.content
        actual = hashlib.sha256(body).hexdigest()
        if response.status_code != 200 or not body.startswith(b'%PDF') or actual != source['expected_sha256']:
            raise ValueError('Approved PDF changed or unavailable: ' + row['candidate_id'])
        proof.append({'candidate_id': row['candidate_id'], 'content_sha256': row['content_sha256'],
                      'source_url': url, 'pdf_sha256': actual, 'bytes': len(body),
                      'checked_at': datetime.now(timezone.utc).isoformat(), 'status': 'passed'})
        print('Verified exact approved PDF:', row['candidate_id'], flush=True)
    return proof


if __name__ == '__main__':
    manifest = json.loads(Path(sys.argv[1]).read_text())
    proof = validate_sources(manifest)
    output = Path('data/content_review_release_receipts') / (manifest['release_id'] + '-source-validation.json')
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps({'release_id': manifest['release_id'], 'records': proof}, indent=2) + '\n')

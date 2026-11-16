"""Fixed-origin, read-only verifier for the *held* historical ALEX baseline.

This is an offline candidate, not wired into a production route. It authenticates
specific GitHub API/job-log observations and Git blob contents. The old
citation job logged three OpenAlex failures: a successful verification therefore
never authorizes citation completion, provider access, publication, or release.
The pending partition requires a separately verified private store and fence.
"""
from __future__ import annotations

import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat
import urllib.error
import urllib.parse
import urllib.request

ROOT = 'https://api.github.com/repos/RISEInfoSec/Alex'
REPOSITORY_ID = 1203144690
RUN_ID = 42171644273
WORKFLOW_ID = 265427042
SOURCE_SHA = '86a28ed580192ee56d3c58485d8f7e1252c05437'
JOBS = {
    127741876259: {
        'name': 'chain', 'log_sha256': 'bf54afac3a936f6c41c6e55d395c5e8d79d8e4af831aaa516bb4ffe481c743f6',
        'steps': ('Pull pipeline state', 'Citation chain', 'Preserve candidates and provider cooldown'),
        'transitions': ('state: pulled pipeline-state@48aa375', 'state: pushed pipeline-state@717d850'),
        'started_at': '2026-11-06T06:03:27Z', 'completed_at': '2026-11-06T06:11:04Z',
    },
    127744388158: {
        'name': 'score', 'log_sha256': 'c5e3e3466449700f2328ad5c10378da3614b0ec8ebff68093a75b0d505535c53',
        'steps': ('Pull pipeline state', 'Quality gate'),
        'transitions': ('state: pulled pipeline-state@717d850', 'state: pushed pipeline-state@a876fe6'),
        'started_at': '2026-11-06T06:11:07Z', 'completed_at': '2026-11-06T06:12:31Z',
    },
}
STATES = (
    ('48aa375c6d222de248e9a343ea6e94535f095e2b', '494256d45e4678823ec7019ac96f5e50cd20aa15',
     '9883e583a6c8ff4810e45c094be23f3c0bd721a4', 'a7fa0235c701035c52ab2891ac668ff2c85637cc25cab45960fe70dbfd69abff', 'citation-input-48aa375.csv.gz'),
    ('717d8505b3489836bc65c393ede0b64fce75a592', '2183355ddf931e23f8e1241415bd7c04c4379408',
     '10e9d0e761690c401d93880f1a5a96d30bbadae8', '1fd0d7f3ffddbe951fd62d03dd3e2520332bf3f66dd855d1742a425fb5b8b90b', 'citation-output-717d850.csv.gz'),
    ('a876fe634e9ea120afc799c583b7e2cb693016b2', '34d35d7fddcbd0ed7e48894f2a7fa3ef43cc16e7',
     'e1a1341b380eeac2761fe4efedfec43e097452c0', '6866cbab913eeabc24396b8c41533d88a02bd2ca8827d12023ca9be483fdcf3d', 'quality-output-a876fe6.csv.gz'),
    ('4d6467b1984da1903b9d4262f92b2d7e38cfeddc', '5b0c0b471d55dacc650bb881665443dbfd8fa17a',
     '74daa2a2c0e4d4447676201e4cb5efd323286a2d', 'e4d68127a0b1e44aa3bc0ee1fbf0ba4a4d4fb725918f599101c2756e03aba446', 'discovery_candidates.csv.gz'),
)
ACTION_PINS = (
    "Download action repository 'actions/checkout@v7.0.1' (SHA:3d3c42e5aac5ba805825da76410c181273ba90b1)",
    "Download action repository 'actions/setup-python@v7.1.0' (SHA:6d4fd22b20465ccc0f7354476588e8df7c9ca0e0)",
)
_STORAGE_HOST = re.compile(r'^productionresults[a-z0-9]+\.blob\.core\.windows\.net$')


class EvidenceUnavailable(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


class GitHubReadOnly:
    """Fixed-origin GitHub GETs; never send GitHub auth to log-storage hosts."""
    def __init__(self, token: str):
        if not isinstance(token, str) or not token or len(token) > 4096 or '\r' in token or '\n' in token:
            raise EvidenceUnavailable('GitHub read credential unavailable')
        self._token = token
        self._opener = urllib.request.build_opener(_NoRedirect)

    def _request(self, path: str):
        if not re.fullmatch(r'/[A-Za-z0-9_./-]+', path) or '..' in path:
            raise EvidenceUnavailable('GitHub path invalid')
        return urllib.request.Request(ROOT + path, headers={
            'Authorization': 'Bearer ' + self._token, 'Accept': 'application/vnd.github+json',
            'User-Agent': 'ALEX-Held-Provenance-Verification'})

    def json(self, path: str):
        try:
            with self._opener.open(self._request(path), timeout=30) as response:
                if response.status != 200:
                    raise ValueError
                raw = response.read(2_000_001)
            if len(raw) > 2_000_000:
                raise ValueError
            value = json.loads(raw)
            if not isinstance(value, dict):
                raise ValueError
            return value
        except Exception:
            raise EvidenceUnavailable('GitHub metadata unavailable') from None

    def log(self, job_id: int) -> bytes:
        try:
            try:
                with self._opener.open(self._request(f'/actions/jobs/{job_id}/logs'), timeout=30):
                    raise ValueError
            except urllib.error.HTTPError as response:
                if response.code != 302:
                    raise ValueError
                location = response.headers.get('Location', '')
            parsed = urllib.parse.urlsplit(location)
            if (parsed.scheme != 'https' or parsed.username or parsed.password or parsed.port not in (None, 443)
                    or not _STORAGE_HOST.fullmatch(parsed.hostname or '') or not parsed.query):
                raise ValueError
            # A fresh request carries no GitHub Authorization header. The
            # signed URL remains in memory and is never logged or returned.
            request = urllib.request.Request(location, headers={'User-Agent': 'ALEX-Held-Provenance-Verification'})
            with self._opener.open(request, timeout=30) as response:
                if response.status != 200:
                    raise ValueError
                raw = response.read(5_000_001)
            if len(raw) > 5_000_000:
                raise ValueError
            # Pin the connector's UTF-8 text representation without dropping
            # a BOM; invalid byte sequences fail closed.
            return raw.decode('utf-8', errors='strict').encode('utf-8')
        except Exception:
            raise EvidenceUnavailable('GitHub job log unavailable') from None


def _blob_hashes(path: Path, expected_git: str, expected_plain: str):
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as stream:
            if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                raise ValueError
            raw = stream.read(64 * 1024 * 1024 + 1)
        if not 0 < len(raw) <= 64 * 1024 * 1024:
            raise ValueError
        git = hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw)
        plain = hashlib.sha256()
        total = 0
        with gzip.GzipFile(fileobj=io.BytesIO(raw), mode='rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                total += len(chunk)
                if total > 128 * 1024 * 1024:
                    raise ValueError
                plain.update(chunk)
        if git.hexdigest() != expected_git or plain.hexdigest() != expected_plain:
            raise ValueError
    except (OSError, ValueError, EOFError):
        raise EvidenceUnavailable('local historical blob mismatch') from None


def _check_job(job, job_id, spec):
    if (job.get('id') != job_id or job.get('run_id') != RUN_ID or job.get('run_attempt') != 1
            or job.get('name') != spec['name'] or job.get('status') != 'completed'
            or job.get('conclusion') != 'success' or job.get('head_sha') != SOURCE_SHA
            or job.get('started_at') != spec['started_at'] or job.get('completed_at') != spec['completed_at']):
        raise EvidenceUnavailable('historical job metadata mismatch')
    steps = job.get('steps')
    if not isinstance(steps, list):
        raise EvidenceUnavailable('historical job steps unavailable')
    for name in spec['steps']:
        matches = [step for step in steps if step.get('name') == name]
        if len(matches) != 1 or matches[0].get('status') != 'completed' or matches[0].get('conclusion') != 'success':
            raise EvidenceUnavailable('historical job step mismatch')


def _verify(reader, directory: Path, *, jobs=JOBS, states=STATES):
    """Internal verifier; fixture substitutions must never reach a live route."""
    run = reader.json(f'/actions/runs/{RUN_ID}/attempts/1')
    if (run.get('id') != RUN_ID or run.get('run_attempt') != 1 or run.get('workflow_id') != WORKFLOW_ID
            or run.get('status') != 'completed' or run.get('conclusion') != 'cancelled'
            or run.get('head_sha') != SOURCE_SHA or run.get('event') != 'workflow_dispatch'
            or run.get('repository', {}).get('id') != REPOSITORY_ID
            or run.get('repository', {}).get('full_name') != 'RISEInfoSec/Alex'):
        raise EvidenceUnavailable('historical run metadata mismatch')
    warning_count = 0
    for job_id, spec in jobs.items():
        _check_job(reader.json(f'/actions/jobs/{job_id}'), job_id, spec)
        log = reader.log(job_id)
        if hashlib.sha256(log).hexdigest() != spec['log_sha256']:
            raise EvidenceUnavailable('historical job log hash mismatch')
        text = log.decode('utf-8', errors='strict')
        for marker in (SOURCE_SHA, *ACTION_PINS, *spec['transitions']):
            if text.count(marker) != 1:
                raise EvidenceUnavailable('historical job log transition mismatch')
        if spec['name'] == 'chain':
            warning_count = sum('400 Client Error' in line and 'api.openalex.org/works' in line for line in text.splitlines())
    if warning_count != 3:
        raise EvidenceUnavailable('historical citation failure count mismatch')
    for commit, tree_sha, blob, plain_sha, filename in states:
        commit_data = reader.json('/git/commits/' + commit)
        if commit_data.get('sha') != commit or commit_data.get('tree', {}).get('sha') != tree_sha:
            raise EvidenceUnavailable('historical commit or tree mismatch')
        tree = reader.json('/git/trees/' + tree_sha)
        if tree.get('sha') != tree_sha or tree.get('truncated') is not False or not isinstance(tree.get('tree'), list):
            raise EvidenceUnavailable('historical tree unavailable')
        entries = [entry for entry in tree['tree'] if entry.get('path') == 'discovery_candidates.csv.gz']
        if len(entries) != 1 or entries[0].get('type') != 'blob' or entries[0].get('sha') != blob:
            raise EvidenceUnavailable('historical candidate blob mismatch')
        _blob_hashes(directory / filename, blob, plain_sha)
    return {'status': 'historical_outputs_verified_held', 'citation_http_400_count': warning_count,
            'citation_complete': False, 'publication_authorized': False, 'provider_access_authorized': False,
            'global_fence_verified': False, 'pending_partition_verified': False}


def verify_held_legacy_provenance(directory: Path):
    """Live GitHub reader only; no fixture adapter or request-supplied pins."""
    try:
        token = os.environ.get('GITHUB_TOKEN', '')
        return _verify(GitHubReadOnly(token), Path(directory))
    except Exception:
        return {'status': 'unavailable', 'citation_complete': False, 'publication_authorized': False,
                'provider_access_authorized': False, 'global_fence_verified': False,
                'pending_partition_verified': False}

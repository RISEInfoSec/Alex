"""An advisory, immutable preference for one genuine weekly worker run."""
from contextlib import contextmanager
from contextvars import ContextVar
from http.client import HTTPException
import json
import re
import signal
from threading import current_thread, main_thread
from urllib.request import Request, build_opener

from tools.content_review.site_reconcile_client import NoRedirect


URL = 'https://alex-research-review.neil-schwartzm917549.chatgpt.site/api/weekly-publication-priorities'
MAX_BYTES = 640 * 1024
MAX_ITEMS = 2000
READ_SECONDS = 4
EMPTY = frozenset()
_current = ContextVar('weekly_publication_priorities', default=(None, EMPTY))
ID = re.compile(r'weekly-[A-Za-z0-9_-]{1,180}')
SHA = re.compile(r'[0-9a-f]{64}')


def read_priorities(token):
    # Native entry runs on the main POSIX thread. A socket's inactivity timeout
    # alone cannot protect the slot against slow streaming or a stuck resolver.
    # If another caller owns the process timer, continue ordinary scheduling.
    if (current_thread() is not main_thread() or signal.getsignal(signal.SIGALRM) != signal.SIG_DFL
            or signal.getitimer(signal.ITIMER_REAL) != (0.0, 0.0)):
        return EMPTY

    def expire(signum, frame):
        raise TimeoutError('Optional weekly priority read expired')

    previous = signal.signal(signal.SIGALRM, expire)
    try:
        signal.setitimer(signal.ITIMER_REAL, READ_SECONDS)
        return _read(token)
    except (HTTPException, OSError, ValueError, RecursionError):
        return EMPTY
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)


def _read(token):
    # The bearer is only valid for this fixed private Site. Never attach it to a
    # redirect, a provider, a persisted record, or a report.
    request = Request(URL, method='GET', headers={'Accept': 'application/json', 'Cache-Control': 'no-cache'})
    request.add_unredirected_header('OAI-Sites-Authorization', 'Bearer ' + token)
    with build_opener(NoRedirect).open(request, timeout=READ_SECONDS) as response:
        if response.status != 200 or response.geturl() != URL:
            return EMPTY
        if 'no-store' not in {value.strip().lower() for value in response.headers.get('Cache-Control', '').split(',')}:
            return EMPTY
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        return EMPTY
    data = json.loads(raw.decode('utf-8'))
    if not isinstance(data, dict) or set(data) != {'priorities'}:
        return EMPTY
    items = data['priorities']
    if not isinstance(items, list) or len(items) > MAX_ITEMS:
        return EMPTY
    pairs = set()
    for item in items:
        if not isinstance(item, dict) or set(item) != {'candidate_id', 'content_sha256'}:
            return EMPTY
        cid, sha = item['candidate_id'], item['content_sha256']
        if not isinstance(cid, str) or not ID.fullmatch(cid) or not isinstance(sha, str) or not SHA.fullmatch(sha):
            return EMPTY
        pairs.add((cid, sha))
    return frozenset(pairs)



@contextmanager
def priority_window(run_id, pairs):
    saved = _current.set((run_id, frozenset(pairs)))
    try:
        yield
    finally:
        _current.reset(saved)


def for_run(run_id):
    owner, pairs = _current.get()
    return pairs if owner == run_id else EMPTY


def prioritize_peers(items, identity, flags, *, preferred_per_turn, ordinary_first=False):
    """Reorder one existing rank, preserving its rotation in each group."""
    if not flags:
        return items
    preferred, ordinary = [], []
    for item in items:
        (preferred if identity(item) in flags else ordinary).append(item)
    if not preferred or not ordinary:
        return items
    result = []
    first = 0
    if ordinary_first:
        result.append(ordinary[0])
        first = 1
    # With both queues populated, an ordinary candidate gets one place per
    # group including a five-paper source reservation or a short artifact scan.
    index = 0
    for item in ordinary[first:]:
        result.extend(preferred[index:index + preferred_per_turn])
        index += preferred_per_turn
        result.append(item)
    result.extend(preferred[index:])
    return result

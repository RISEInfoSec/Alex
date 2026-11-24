"""Read Git objects through the official Git Database API into a private local checkout.

Every object must reproduce the requested Git identity. Only the three established
coordinator refs are read. The API transport never writes to GitHub.
"""
import base64
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.request import Request, build_opener

from tools.content_review.site_reconcile_client import NoRedirect

ROOT = 'https://api.github.com/repos/RISEInfoSec/Alex'
REFS = ('refs/heads/codex/soups-corpus-review', 'refs/heads/main', 'refs/heads/codex/content-review-heartbeat')
SHA = re.compile('[0-9a-f]{40}')
MAX = 48 * 1024 * 1024


def api(path):
    # Scope is fixed by code. The managed read token is never placed on argv.
    headers = {'Accept': 'application/vnd.github+json', 'User-Agent': 'ALEX source coordinator object reader',
               'Cache-Control': 'no-cache'}
    token = os.environ.get('ALEX_GITHUB_TOKEN')
    if token:
        headers['Authorization'] = 'Bearer ' + token
    with build_opener(NoRedirect).open(Request(ROOT + path, headers=headers), timeout=30) as response:
        data = response.read(MAX + 1)
    if len(data) > MAX:
        raise ValueError('GitHub object response exceeds transport limit')
    return json.loads(data)


def git(repo, *args, data=None):
    return subprocess.run(['git', '-C', str(repo), *args], input=data, check=True,
                          capture_output=True, timeout=45).stdout


def identity(kind, data):
    return hashlib.sha1(kind.encode() + b' ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def save(repo, kind, sha, data):
    if identity(kind, data) != sha:
        raise ValueError('Immutable Git object identity differs')
    got = git(repo, 'hash-object', '-w', '-t', kind, '--stdin', data=data).decode().strip()
    if got != sha:
        raise ValueError('Local Git object identity differs')


def exists(repo, sha):
    return subprocess.run(['git', '-C', str(repo), 'cat-file', '-e', sha],
                          capture_output=True, timeout=10).returncode == 0


def commit_bytes(sha, obj):
    """REST normalizes time zones. Accept a reconstruction only on an exact SHA."""
    verification = obj.get('verification') or {}
    if verification.get('payload') and verification.get('signature'):
        headers, gap, message = verification['payload'].partition('\n\n')
        sig = verification['signature'].rstrip('\n').replace('\n','\n ')
        for sigend in ('', '\n '):
            for end in ('', '\n'):
                value = (headers + '\ngpgsig ' + sig + sigend + gap + message + end).encode()
                if identity('commit', value) == sha:
                    return value
        raise ValueError('Signed Git commit cannot be reproduced')
    zones = ['+0000', '-0500', '-0400', '-0000']
    zones += [f'{sign}{n//60:02}{n%60:02}' for sign in '+-' for n in range(15, 14*60+1, 15)]
    zones = list(dict.fromkeys(zones))
    headers = ['tree ' + obj['tree']['sha'], *['parent ' + p['sha'] for p in obj['parents']]]
    def person(key):
        value = obj[key]
        ts = int(datetime.fromisoformat(value['date']).timestamp())
        return f'{key} {value["name"]} <{value["email"]}> {ts} '
    head = '\n'.join(headers) + '\n' + person('author')
    committer = '\n' + person('committer')
    ends = [obj['message'] + suffix for suffix in ('', '\n', '\n\n')]
    pairs = [(z,z) for z in zones]
    pairs.extend((a,b) for a in zones for b in zones if a != b)
    for a, b in pairs:
        prefix = head + a + committer + b + '\n\n'
        for message in ends:
            value = (prefix + message).encode()
            if identity('commit', value) == sha:
                return value
    raise ValueError('Unsigned Git commit cannot be reproduced')


def refs():
    def read(ref):
        value = api('/git/ref/' + ref.removeprefix('refs/'))
        if value.get('ref') != ref or value.get('object',{}).get('type') != 'commit':
            raise ValueError('GitHub ref metadata differs')
        sha = value['object']['sha']
        if not SHA.fullmatch(sha):
            raise ValueError('GitHub ref identity invalid')
        return ref, sha
    with ThreadPoolExecutor(max_workers=3) as pool:
        return dict(pool.map(read, REFS))


def tree(repo, root):
    if exists(repo, root):
        return
    doc = api('/git/trees/' + root + '?recursive=1')
    if doc.get('sha') != root or doc.get('truncated') is not False:
        raise ValueError('Complete Git tree unavailable')
    trees_from_entries(repo, root, doc['tree'])


def trees_from_entries(repo, root, entries):
    groups = {'': []}
    expected = {'': root}
    for item in entries:
        path = item['path']
        parent, _, name = path.rpartition('/')
        if not name or not SHA.fullmatch(item['sha']) or item['type'] not in ('tree','blob'):
            raise ValueError('Invalid Git tree entry')
        groups.setdefault(parent, []).append((name, item))
        if item['type'] == 'tree':
            expected[path] = item['sha']
            groups.setdefault(path, [])
    for path in sorted(groups,key=lambda name:name.count('/') + bool(name),reverse=True):
        children=groups[path]
        raw = bytearray()
        for name, row in sorted(children, key=lambda r:(r[0] + ('/' if r[1]['type']=='tree' else '')).encode()):
            raw.extend(row['mode'].lstrip('0').encode() + b' ' + name.encode() + b'\0' + bytes.fromhex(row['sha']))
        if not exists(repo, expected[path]):
            save(repo, 'tree', expected[path], bytes(raw))


def blob(repo, sha):
    if exists(repo, sha):
        return
    doc = api('/git/blobs/' + sha)
    if doc.get('sha') != sha or doc.get('encoding') != 'base64' or not 0 <= doc.get('size', -1) <= 32*1024*1024:
        raise ValueError('Git blob metadata invalid')
    raw = base64.b64decode(''.join(doc['content'].split()), validate=True)
    if len(raw) != doc['size']:
        raise ValueError('Git blob length differs')
    save(repo, 'blob', sha, raw)


def commit(repo, sha):
    if not exists(repo, sha):
        doc = api('/git/commits/' + sha)
        if doc.get('sha') != sha:
            raise ValueError('Git commit identity differs')
        save(repo, 'commit', sha, commit_bytes(sha, doc))
    root = git(repo, 'cat-file', '-p', sha).splitlines()[0].decode().removeprefix('tree ')
    if not SHA.fullmatch(root):
        raise ValueError('Git commit tree invalid')
    tree(repo, root)


_ready_trees=set()


def hydrate_checkout(repo, sha):
    """Prepare every blob required by the existing prospective Git tree guard."""
    commit(repo, sha)
    key=(str(Path(repo).resolve()),sha)
    if key in _ready_trees:
        return
    raw=git(repo,'ls-tree','-r','-z',sha)
    entries={item.split(b'\t',1)[0].split()[2].decode() for item in raw.rstrip(b'\0').split(b'\0') if item}
    if len(entries)>10000 or any(not SHA.fullmatch(x) for x in entries):
        raise ValueError('Source checkout exceeds bounded Git inventory')
    states=git(repo,'cat-file','--batch-check=%(objectname) %(objecttype)',data=('\n'.join(sorted(entries))+'\n').encode()).decode().splitlines()
    if len(states)!=len(entries):
        raise ValueError('Local Git inventory incomplete')
    missing=[]
    for expected,state in zip(sorted(entries),states):
        if state==expected+' missing':missing.append(expected)
        elif state!=expected+' blob':raise ValueError('Local Git inventory differs')
    if len(missing)>80:
        raise ValueError('Source checkout needs a current verified base archive')
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(lambda x:blob(repo,x),missing))
    _ready_trees.add(key)


def ancestry(repo, ancestor, head):
    # Trace real Git parent links. An unrelated or absent parent cannot prove
    # ancestry. This also works without ancestors older than the desired source.
    result = subprocess.run(['git','-C',str(repo),'merge-base','--is-ancestor',ancestor,head],capture_output=True)
    if result.returncode == 0:
        return
    compare = api(f'/compare/{ancestor}...{head}?per_page=1')
    if compare.get('status') not in ('ahead','identical') or compare.get('behind_by') != 0:
        raise ValueError('Source commit is not an ancestor')
    ahead = compare.get('ahead_by')
    if type(ahead) is not int or not 0 <= ahead <= 1000:
        raise ValueError('Source history exceeds bounded range')
    links = {}
    for page in range(1, (ahead+99)//100+1):
        rows = api(f'/compare/{ancestor}...{head}?per_page=100&page={page}').get('commits')
        if not isinstance(rows,list) or not 1 <= len(rows) <= 100:
            raise ValueError('Git comparison history incomplete')
        for row in rows:
            sha = row['sha']
            if not SHA.fullmatch(sha):
                raise ValueError('Invalid Git comparison commit')
            if not exists(repo,sha):
                obj = {**row['commit'], 'parents': row['parents']}
                save(repo, 'commit', sha, commit_bytes(sha, obj))
            # Read the parent edges back from the exact Git commit object.
            raw = git(repo,'cat-file','commit',sha)
            if identity('commit',raw) != sha:
                raise ValueError('Local Git ancestry object differs')
            links[sha] = [line[7:].decode() for line in raw.partition(b'\n\n')[0].splitlines() if line.startswith(b'parent ')]
    frontier = [head]
    seen = set()
    while frontier:
        value = frontier.pop()
        if value == ancestor:
            commit(repo, ancestor)
            return
        if value not in seen:
            seen.add(value)
            frontier.extend(links.get(value, []))
    raise ValueError('No immutable Git ancestry path from head to source')


def prepare_git(repo, args):
    if not args:
        return
    if args[0]=='merge-base' and len(args)==4 and args[1]=='--is-ancestor':
        if all(SHA.fullmatch(x) for x in args[2:]):
            ancestry(repo,args[2],args[3])
            return b''
    elif args[0]=='cat-file' and len(args)==3 and args[1] in ('-s','blob') and SHA.fullmatch(args[2]):
        blob(repo,args[2])
    elif args[0] in ('rev-list','ls-tree','diff-tree','rev-parse'):
        values=[v for v in args[1:] if SHA.fullmatch(v.replace('^{tree}',''))]
        for value in values:
            sha=value.removesuffix('^{tree}')
            commit(repo,sha)
            if args[0] in ('rev-list','diff-tree'):
                raw=git(repo,'cat-file','-p',sha).partition(b'\n\n')[0]
                for line in raw.splitlines():
                    if line.startswith(b'parent '):
                        commit(repo,line[7:].decode())

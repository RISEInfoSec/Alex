"""Lossless bounded transport for native GitHub checkpoints.

Never print a whole checkpoint into an execution-tool response. Each read is
bounded to 32 KiB of UTF-8 text; callers assemble in tool memory, parse JSON,
create a blob, and MUST compare the returned Git SHA with metadata before
creating a tree. A successful API call is not an integrity check.
"""
import argparse
import hashlib
import json
import re
from pathlib import Path

CHUNK_CHARS = 32768
OMITTED = re.compile(r'(?:\.\.\.\s*\d+\s+(?:bytes|chars|tokens)\s+(?:omitted|truncated)|\[\s*(?:\.\.\.)?truncated\s*\])', re.I)

def validate(content, path=''):
    if str(path).endswith('.json'):
        if OMITTED.search(content):
            raise ValueError('Truncated checkpoint transport; do not write')
        return json.loads(content)

def metadata(path):
    path = Path(path)
    content = path.read_text()
    validate(content, path)
    data = content.encode('utf-8')
    return dict(path=str(path), characters=len(content), size=len(data),
                sha256=hashlib.sha256(data).hexdigest(),
                git_blob_sha=hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest(),
                chunk_chars=CHUNK_CHARS, chunks=(len(content)+CHUNK_CHARS-1)//CHUNK_CHARS)

def chunk(path, index):
    content = Path(path).read_text()
    validate(content, path)
    start = index * CHUNK_CHARS
    if index < 0 or start >= len(content):
        raise ValueError('Invalid chunk index')
    return dict(index=index, content=content[start:start+CHUNK_CHARS])

if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path'); parser.add_argument('--chunk',type=int)
    args=parser.parse_args()
    print(json.dumps(metadata(args.path) if args.chunk is None else chunk(args.path,args.chunk),ensure_ascii=False))

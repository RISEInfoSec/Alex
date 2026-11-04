"""Verify complete immutable Git content before parsing or overwriting it."""
import argparse, hashlib, json
from pathlib import Path

def verify_bytes(content, blob_sha, size):
    if isinstance(content,str):content=content.encode('utf-8')
    actual=hashlib.sha1(b'blob '+str(len(content)).encode()+b'\0'+content).hexdigest()
    if len(content)!=size or actual!=blob_sha:raise ValueError('Incomplete or altered Git blob; do not reconstruct or write this snapshot')
    return {'blob_sha':actual,'size':len(content),'sha256':hashlib.sha256(content).hexdigest()}

def main():
    p=argparse.ArgumentParser();p.add_argument('path',type=Path);p.add_argument('--blob-sha',required=True);p.add_argument('--size',type=int,required=True);a=p.parse_args()
    print(json.dumps(verify_bytes(a.path.read_bytes(),a.blob_sha,a.size)))
if __name__=='__main__':main()

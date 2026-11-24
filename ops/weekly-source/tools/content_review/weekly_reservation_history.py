"""Check the source writer's existing single-parent history rule before selecting a retained result."""
import os
import subprocess
import time

from tools.content_review.github_read_objects import SHA, api


def reachable_reservations(repo, head, ancestors, *, get=api):
    if not ancestors:
        return set()
    if not SHA.fullmatch(head) or not all(isinstance(value,str) and SHA.fullmatch(value) for value in ancestors):
        raise ValueError('Invalid source reservation commitment')
    expected=head
    verified=set()
    deadline=time.monotonic()+15
    for page in range(1, 11):
        if time.monotonic()>=deadline:
            break
        if os.environ.get('ALEX_SOURCE_READ_TRANSPORT')=='github-rest':
            rows=get(f'/commits?sha={head}&per_page=50&page={page}',timeout=4)
            entries=[(r['sha'],[parent['sha'] for parent in r['parents']]) for r in rows]
        else:
            raw=subprocess.run(['git','-C',str(repo),'rev-list','--first-parent','--parents','--max-count=50',f'--skip={(page-1)*50}',head],capture_output=True,check=True,timeout=4).stdout
            entries=[(parts[0],parts[1:]) for line in raw.decode('ascii').splitlines() if (parts:=line.split())]
        for sha,parents in entries:
            if sha!=expected or len(parents)!=1 or not SHA.fullmatch(parents[0]):
                return verified
            if sha in ancestors:
                verified.add(sha)
                if verified==ancestors:
                    return verified
            expected=parents[0]
        if len(entries)<50:
            break
    return verified

"""Bounded read-only Git and process-capacity check for the scheduled worker.

Only aggregate process counts and fixed error categories are returned. This
does not take a lease, contact a source provider, or expose Git output.
"""
from pathlib import Path
import json
import os
import resource
import time

from tools.content_review.coordinator_heartbeat_transport import SAFE_GIT_ERRORS,fetch_heads,read_heads

MIN_PROCESS_SLOTS=4
SAFE_ERRORS=SAFE_GIT_ERRORS|frozenset({'Coordinator Git object verification failed',
    'Coordinator repository remote differs','Coordinator remote refs invalid','Coordinator remote refs incomplete',
    'Invalid coordinator fetch'})


def capacity():
    total=zombies=same_uid=unreadable=0;uid=os.getuid()
    for path in Path('/proc').iterdir():
        if not path.name.isdigit():continue
        try:
            stat=(path/'stat').read_text();tail=stat[stat.rfind(')')+2:].split()
            if not tail:raise ValueError('invalid process state')
            total+=1;zombies+=tail[0]=='Z';same_uid+=path.stat().st_uid==uid
        except FileNotFoundError:continue
        except (OSError,ValueError,IndexError):unreadable+=1
    def cgroup(name):
        try:
            raw=(Path('/sys/fs/cgroup')/name).read_text().strip()
            if raw=='max':return None
            value=int(raw);return value if value>=0 else None
        except (OSError,ValueError):return None
    current,maximum=cgroup('pids.current'),cgroup('pids.max')
    try:soft,_=resource.getrlimit(resource.RLIMIT_NPROC)
    except (OSError,ValueError):soft=resource.RLIM_INFINITY
    soft=None if soft==resource.RLIM_INFINITY else soft
    exhausted=((current is not None and maximum is not None and maximum-current<MIN_PROCESS_SLOTS) or
               (soft is not None and soft-same_uid<MIN_PROCESS_SLOTS))
    return {'visible_processes':total,'zombies':zombies,'same_uid_processes':same_uid,'unreadable_processes':unreadable,
            'cgroup_current':current,'cgroup_max':maximum,'user_soft_limit':soft,'capacity_exhausted':exhausted}


def run(repo,*,capacity_reader=capacity,heads=read_heads,fetch=fetch_heads,clock=time.monotonic):
    try:info=capacity_reader()
    except Exception:return {'status':'blocked','reason':'process_capacity_unavailable','candidate_processing':False}
    if not isinstance(info,dict) or type(info.get('capacity_exhausted')) is not bool:
        return {'status':'blocked','reason':'process_capacity_unavailable','candidate_processing':False}
    if info['capacity_exhausted']:
        return {'status':'blocked','reason':'process_capacity_exhausted','capacity':info,'candidate_processing':False}
    started=clock()
    try:
        refs=heads(repo);observed=clock();fetch(repo,refs,'git-preflight');finished=clock()
    except Exception as exc:
        reason=str(exc) if str(exc) in SAFE_ERRORS else 'git_preflight_unavailable'
        return {'status':'blocked','reason':reason,'capacity':info,'candidate_processing':False}
    return {'status':'ready','reason':None,'capacity':info,'refs_verified':True,
            'read_heads_ms':round((observed-started)*1000),'fetch_heads_ms':round((finished-observed)*1000),
            'candidate_processing':False}


def main():
    result=run(Path.cwd());print(json.dumps(result,sort_keys=True));return 0 if result['status']=='ready' else 1


if __name__=='__main__':raise SystemExit(main())

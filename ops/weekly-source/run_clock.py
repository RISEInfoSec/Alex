"""Operate one running hourly source slot, or do a read-only cache/receipt check."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import sys

HERE=Path(__file__).resolve().parent
if '.pyz' not in __file__:
    sys.path[:0]=[str(HERE),'/workspace/work/preservation/codex_soups-corpus-review']
from setup_checkout import setup
from tools.content_review.github_read_objects import REFS
from tools.content_review.source_clock_state import inspect
from tools.content_review.verified_inputs import load_inputs
from tools.content_review.weekly_source_clock import main as native_main


def main():
    parser=argparse.ArgumentParser()
    mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--prime',action='store_true')
    mode.add_argument('--inspect',nargs='?',const='',metavar='NATIVE_UUID')
    parser.add_argument('--cache',type=Path,default=Path('/workspace/work/alex-weekly-source-cache'))
    args=parser.parse_args()
    os.environ['ALEX_SOURCE_READ_TRANSPORT']='github-rest'
    cache=args.cache.resolve()
    cache.mkdir(mode=0o700,parents=True,exist_ok=True)
    repo=cache/'repo'
    with (cache/'source-clock.lock').open('a') as lock:
        try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError:
            print(json.dumps({'status':'blocked','reason':'source_operator_running'}));return 1
        heads=setup(repo)
        os.chdir(repo)
        if args.prime:
            inputs=load_inputs(repo,heads[REFS[0]],heads[REFS[1]])
            print(json.dumps({'status':'read_only_ready','heads':heads,'inputs':inputs['counts'],'writes':0,'provider_sends':0}))
            return 0
        if args.inspect is not None:
            print(json.dumps(inspect(repo,args.inspect or None)))
            return 0
        return native_main()


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as error:
        print(json.dumps({'status':'blocked','reason':'source_start_or_readback_unavailable','stage':'checkout_or_inspection','error_type':type(error).__name__}))
        raise SystemExit(1)

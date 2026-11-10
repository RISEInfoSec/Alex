import os
import subprocess
import sys
from pathlib import Path

RUNNER=Path(__file__).resolve().parents[1]/'scripts/run_offline_tests.py'


def test_runner_blocks_socket_and_preserves_git_configuration(tmp_path):
    env={**os.environ,'GIT_CONFIG_COUNT':'1','GIT_CONFIG_KEY_0':'test.key','GIT_CONFIG_VALUE_0':'value'}
    code='''import errno,os,socket
assert os.environ['GIT_CONFIG_KEY_0']=='test.key'
assert os.environ['GIT_CONFIG_VALUE_0']=='value'
assert os.environ['GIT_CONFIG_COUNT']=='2'
assert os.environ['GIT_CONFIG_KEY_1']=='maintenance.auto'
assert os.environ['GIT_CONFIG_VALUE_1']=='false'
try: socket.socket()
except OSError as e: assert e.errno==errno.EPERM
else: raise AssertionError('socket unexpectedly allowed')
'''
    result=subprocess.run([sys.executable,str(RUNNER),'-c',code],env=env,capture_output=True,text=True)
    assert result.returncode==0,result.stderr


def test_runner_waits_for_adopted_child_and_preserves_exit(tmp_path):
    marker=tmp_path/'finished'
    code='''import os,sys,time
pid=os.fork()
if pid==0:
 time.sleep(0.1)
 open(sys.argv[1],'w').write('finished')
 os._exit(0)
os._exit(7)
'''
    result=subprocess.run([sys.executable,str(RUNNER),'-c',code,str(marker)],capture_output=True,text=True)
    assert result.returncode==7,result.stderr
    assert marker.read_text()=='finished'

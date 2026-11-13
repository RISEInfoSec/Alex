from pathlib import Path
import subprocess
import sys


def test_offline_regressions_cannot_create_a_network_socket():
    root=Path(__file__).resolve().parents[1]
    result=subprocess.run([sys.executable,str(root/'scripts/run_offline_tests.py'),'-c',
                           'import socket; socket.socket()'],capture_output=True,text=True,timeout=15)
    assert result.returncode!=0
    assert 'PermissionError' in result.stderr or 'Operation not permitted' in result.stderr


def test_offline_node_regressions_cannot_connect():
    root=Path(__file__).resolve().parents[1]
    program="require('node:net').connect({host:'127.0.0.1',port:1}).on('error',e=>process.exit(e.code==='EPERM'?0:1))"
    result=subprocess.run([sys.executable,str(root/'scripts/run_offline_tests.py'),'--','node','-e',program],capture_output=True,text=True,timeout=15)
    assert result.returncode==0,result.stderr

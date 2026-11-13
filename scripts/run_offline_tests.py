#!/usr/bin/env python3
"""Run Linux regression tests with network syscalls denied and children reaped."""
from __future__ import annotations
import ctypes
import errno
import os
import subprocess
import sys
import time


def main() -> int:
    if len(sys.argv)<2:
        print('test command required',file=sys.stderr);return 2
    if sys.argv[1]=='--':
        if len(sys.argv)<3:
            print('test command required',file=sys.stderr);return 2
        command=sys.argv[2:]
    else:
        command=[sys.executable,*sys.argv[1:]]
    libc=ctypes.CDLL(None,use_errno=True)
    enabled=ctypes.c_int(0)
    if libc.prctl(36,1,0,0,0)!=0 or libc.prctl(37,ctypes.byref(enabled),0,0,0)!=0 or enabled.value!=1:
        print('child subreaper unavailable',file=sys.stderr);return 1
    try:
        seccomp=ctypes.CDLL('libseccomp.so.2',use_errno=True)
        seccomp.seccomp_init.argtypes=[ctypes.c_uint32];seccomp.seccomp_init.restype=ctypes.c_void_p
        seccomp.seccomp_syscall_resolve_name.argtypes=[ctypes.c_char_p];seccomp.seccomp_syscall_resolve_name.restype=ctypes.c_int
        seccomp.seccomp_rule_add.argtypes=[ctypes.c_void_p,ctypes.c_uint32,ctypes.c_int,ctypes.c_uint];seccomp.seccomp_rule_add.restype=ctypes.c_int
        seccomp.seccomp_load.argtypes=[ctypes.c_void_p];seccomp.seccomp_load.restype=ctypes.c_int
        seccomp.seccomp_release.argtypes=[ctypes.c_void_p]
        context=seccomp.seccomp_init(0x7fff0000)
        if not context: raise RuntimeError('seccomp init failed')
        try:
            for name in (b'socket',b'connect',b'sendto',b'sendmsg',b'sendmmsg'):
                nr=seccomp.seccomp_syscall_resolve_name(name)
                if nr<0 or seccomp.seccomp_rule_add(context,0x00050000 | errno.EPERM,nr,0)!=0:
                    raise RuntimeError('seccomp rule failed')
            if seccomp.seccomp_load(context)!=0: raise RuntimeError('seccomp load failed')
        finally:
            seccomp.seccomp_release(context)
    except (OSError,RuntimeError) as exc:
        print(f'offline test isolation unavailable: {exc}',file=sys.stderr);return 1
    try:
        count=int(os.environ.get('GIT_CONFIG_COUNT','0'))
        if count<0 or count>1000: raise ValueError
    except ValueError:
        print('invalid inherited Git configuration',file=sys.stderr);return 1
    os.environ[f'GIT_CONFIG_KEY_{count}']='maintenance.auto'
    os.environ[f'GIT_CONFIG_VALUE_{count}']='false'
    os.environ['GIT_CONFIG_COUNT']=str(count+1)
    try:
        child=subprocess.Popen(command)
        code=child.wait()
    except OSError:
        print('could not start offline tests',file=sys.stderr);return 1
    deadline=time.monotonic()+30
    while True:
        try:
            pid,_=os.waitpid(-1,os.WNOHANG)
        except ChildProcessError:
            break
        if pid: continue
        if time.monotonic()>=deadline:
            print('offline test child cleanup unconfirmed',file=sys.stderr)
            return code if code>0 else 1
        time.sleep(0.05)
    return code if code>=0 else 128-code


if __name__=='__main__':
    raise SystemExit(main())

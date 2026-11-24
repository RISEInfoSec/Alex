"""Disable echo and canonical line limits before signaling readiness for hidden input."""
import json
import os
import sys
import termios

LIMIT = 1024 * 1024


def hidden_input(stream=sys.stdin, announce=sys.stderr):
    fd=stream.fileno()
    saved=None
    if os.isatty(fd):
        saved=termios.tcgetattr(fd)
        private=termios.tcgetattr(fd)
        private[3] &= ~(termios.ECHO | termios.ECHONL | termios.ICANON)
        private[6][termios.VMIN]=1
        private[6][termios.VTIME]=0
        termios.tcsetattr(fd,termios.TCSAFLUSH,private)
    try:
        print('READY_FOR_PRIVATE_INPUT',file=announce,flush=True)
        data=stream.buffer.readline(LIMIT+1)
        if len(data)>LIMIT or not data.endswith(b'\n'):
            raise ValueError('Invalid bounded private input')
        value=json.loads(data)
        if not isinstance(value,dict) or set(value)!={'site_token','native'} or not isinstance(value['native'],dict):
            raise ValueError('Invalid private worker input')
        return value
    finally:
        if saved is not None:
            termios.tcsetattr(fd,termios.TCSAFLUSH,saved)

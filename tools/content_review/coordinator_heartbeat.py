"""Maintain a bounded detached heartbeat during local coordinator work.

A failed or ambiguous write is sticky: never retry it. The caller must stop
and reconcile the heartbeat ref before attempting any candidate write. The
Site's own keeper takes over only after this context has stopped.
"""
from threading import Event, Lock, Thread


class HeartbeatUnavailable(RuntimeError):
    pass


class HeartbeatKeeper:
    def __init__(self, pulse, *, interval=12, max_pulses=24):
        if not callable(pulse) or not 0 < interval <= 20 or type(max_pulses) is not int or not 1 <= max_pulses <= 24:
            raise ValueError('Invalid bounded heartbeat configuration')
        self._pulse=pulse;self._interval=interval;self._max=max_pulses
        self._stop=Event();self._lock=Lock();self._error=None;self._count=0;self._thread=None

    def _once(self):
        try:
            result=self._pulse()
            if not isinstance(result,dict) or result.get('status')!='committed_and_read_back':
                raise HeartbeatUnavailable('Heartbeat result is unconfirmed; reconcile before retrying')
            with self._lock:self._count+=1
        except Exception as exc:
            with self._lock:self._error=exc
            self._stop.set()

    def _loop(self):
        while not self._stop.wait(self._interval):
            with self._lock:exhausted=self._count>=self._max
            if exhausted:
                with self._lock:self._error=HeartbeatUnavailable('Bounded heartbeat budget exhausted')
                self._stop.set();return
            self._once()

    def __enter__(self):
        if self._thread is not None:raise RuntimeError('Heartbeat keeper cannot be reused')
        self._once();self.check()
        self._thread=Thread(target=self._loop,name='content-review-heartbeat',daemon=True);self._thread.start()
        return self

    def check(self):
        with self._lock:error=self._error
        if error is not None:raise HeartbeatUnavailable('Heartbeat unconfirmed; reconcile before candidate writes') from None

    def __exit__(self,exc_type,exc,tb):
        self._stop.set()
        if self._thread is not None:self._thread.join()
        # A simultaneous application error must not hide an uncertain write.
        self.check()
        return False

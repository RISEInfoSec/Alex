import threading

import pytest

from tools.content_review.coordinator_heartbeat import HeartbeatKeeper,HeartbeatUnavailable


def test_long_work_renews_heartbeat_and_stops_before_return():
    reached=threading.Event();pulses=[]
    def pulse():
        pulses.append(len(pulses)+1)
        if len(pulses)==3:reached.set()
        return {'status':'committed_and_read_back'}
    with HeartbeatKeeper(pulse,interval=.01,max_pulses=8) as keeper:
        assert reached.wait(1)
        keeper.check()
    count=len(pulses)
    assert count>=3 and not threading.Event().wait(.03) and len(pulses)==count


def test_ambiguous_heartbeat_is_sticky_and_never_retried():
    reached=threading.Event();pulses=[]
    def pulse():
        pulses.append(1)
        if len(pulses)==2:reached.set();return {'status':'outcome_unknown'}
        return {'status':'committed_and_read_back'}
    with pytest.raises(HeartbeatUnavailable,match='reconcile'):
        with HeartbeatKeeper(pulse,interval=.01,max_pulses=8) as keeper:
            assert reached.wait(1)
    assert len(pulses)==2


def test_immediate_heartbeat_failure_prevents_work():
    called=[]
    with pytest.raises(HeartbeatUnavailable):
        with HeartbeatKeeper(lambda:{'status':'blocked'},interval=.01):called.append(True)
    assert called==[]


def test_exhausted_heartbeat_budget_stops_the_coordinator():
    with pytest.raises(HeartbeatUnavailable):
        with HeartbeatKeeper(lambda:{'status':'committed_and_read_back'},interval=.01,max_pulses=1) as keeper:
            assert keeper._stop.wait(1)


def test_unknown_heartbeat_takes_precedence_over_a_concurrent_work_error():
    reached=threading.Event();count=[]
    def pulse():
        count.append(1)
        if len(count)==2:reached.set();return {'status':'outcome_unknown'}
        return {'status':'committed_and_read_back'}
    with pytest.raises(HeartbeatUnavailable,match='reconcile'):
        with HeartbeatKeeper(pulse,interval=.01) as keeper:
            assert reached.wait(1)
            raise ValueError('local work failed')
    assert len(count)==2


def test_foreground_refresh_never_overlaps_background_heartbeat():
    lock=threading.Lock();active=[];overlap=[]
    def pulse():
        with lock:
            active.append(1)
            if len(active)>1:overlap.append(True)
        threading.Event().wait(.02)
        with lock:active.pop()
        return {'status':'committed_and_read_back'}
    with HeartbeatKeeper(pulse,interval=.005,max_pulses=8) as keeper:
        threading.Event().wait(.01)
        keeper.refresh()
    assert overlap==[]


def test_refresh_after_ambiguous_heartbeat_never_retries():
    calls=[]
    def pulse():
        calls.append(1)
        return {'status':'committed_and_read_back'} if len(calls)==1 else {'status':'outcome_unknown'}
    with pytest.raises(HeartbeatUnavailable):
        with HeartbeatKeeper(pulse,interval=1) as keeper:
            keeper.refresh()
    assert len(calls)==2


def test_heartbeat_reports_only_allowlisted_failure_categories():
    def fail(message):
        def pulse():raise ValueError(message)
        with pytest.raises(HeartbeatUnavailable) as caught:
            with HeartbeatKeeper(pulse,interval=.01):pass
        return caught.value.safe_cause
    assert fail('Coordinator Git fetch resource_unavailable')=='Coordinator Git fetch resource_unavailable'
    assert fail('private-candidate or token')=='heartbeat_failure_unclassified'

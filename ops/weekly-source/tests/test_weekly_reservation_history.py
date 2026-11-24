from tools.content_review.weekly_reservation_history import reachable_reservations


def test_merge_blocks_older_retention_without_blocking_the_recent_linear_prefix(monkeypatch):
    monkeypatch.setenv('ALEX_SOURCE_READ_TRANSPORT','github-rest')
    first,second,merge,old,side,prior=[s*40 for s in 'abcdef']
    def entry(head,*parents):
        return {'sha':head,'parents':[{'sha':p} for p in parents]}
    page=[entry(first,second),entry(second,merge),entry(merge,old,side),entry(old,prior)]
    assert reachable_reservations(None,first,{old,second},get=lambda *a,**k:page)=={second}
    assert reachable_reservations(None,first,{old},get=lambda *a,**k:page)==set()
    assert reachable_reservations(None,first,{second},get=lambda *a,**k:[entry(side,second)])==set()

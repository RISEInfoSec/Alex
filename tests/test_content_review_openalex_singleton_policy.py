from datetime import datetime, timezone
import pytest

from tools.content_review.openalex_singleton_policy import defer_429, singleton

NOW=datetime(2026,11,8,13,0,tzinfo=timezone.utc)


@pytest.mark.parametrize(('identity','tail'),[
    ('w123456','W123456'),('W1','W1'),('10.7717/peerj.4375','doi:10.7717/peerj.4375')])
def test_only_free_singleton_specs_are_prepared(identity,tail):
    result=singleton(identity)
    assert result['url']=='https://api.openalex.org/works/'+tail and result['method']=='GET'
    assert result['status']=='plan_only' and result['provider_requests']==result['paid_requests']==result['writes']==0
    assert result['credential_required'] is False and result['publication_authorized'] is False
    assert result['requires_atomic_budget_reservation'] and result['requires_native_lease_and_private_decision_fence']


@pytest.mark.parametrize('identity',['',' W1','W0','W1?search=x','W1/../../authors','https://example.test/x',
    '10.1234/foo?filter=x','10.1234/foo#bar','10.1234/foo%2f..','10.1234/foo/bar','10.1234/../x',
    '10.1234/foo@evil.test','10.1234/é',None])
def test_no_arbitrary_urls_or_query_operations_can_be_constructed(identity):
    with pytest.raises(ValueError):singleton(identity)


@pytest.mark.parametrize(('headers','expected'),[
    ({'Retry-After':'120'},'2026-11-08T13:02:00+00:00'),
    ({'retry-after':'0'},'2026-11-08T13:01:00+00:00'),
    ({'Retry-After':'120','X-RateLimit-Reset':'3600'},'2026-11-08T14:00:00+00:00'),
    ({'Retry-After':'Sun, 08 Nov 2026 13:05:00 GMT'},'2026-11-08T13:05:00+00:00'),
    ({'Retry-After':'172800','X-RateLimit-Reset':'invalid'},'2026-11-10T13:00:00+00:00'),
    ({},'2026-11-09T00:00:00+00:00'),
    ({'Retry-After':'invalid'},'2026-11-09T00:00:00+00:00')])
def test_rate_limit_never_retries_automatically_or_before_known_deadlines(headers,expected):
    result=defer_429(headers,at=NOW)
    assert result['status']=='held' and result['resume_not_before']==expected
    assert result['automatic_retry'] is False and result['requires_provider_policy_recheck'] is True and result['writes']==0


def test_unreasonably_distant_cooldown_requires_reconciliation():
    result=defer_429({'Retry-After':'99999999'},at=NOW)
    assert result['status']=='held' and result['resume_not_before'] is None and result['automatic_retry'] is False
    assert defer_429({'Retry-After':'999999999'},at=NOW)['resume_not_before'] is None


def test_ambiguous_duplicate_header_and_naive_time_fail_closed():
    with pytest.raises(ValueError):defer_429({'Retry-After':'1','retry-after':'2'},at=NOW)
    with pytest.raises(ValueError):defer_429({},at=datetime(2026,11,8))

"""Read-only specifications for a future bounded OpenAlex singleton route.

No requests, credentials, budget reservations, retries, or writes occur here.
The live interim worker does not use this module. A future executor must bind
the plan to an authenticated native run, an atomic shared budget reservation,
current private-decision and lease fences, and independently verified results.

OpenAlex documents single-entity lookups as free, keyless access, rate limits,
and Retry-After behavior at https://help.openalex.org/api/get-single-entities/
and https://help.openalex.org/api/authentication/. Provider policy can change;
this offline specification is not proof of the current cost or availability.
"""
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
import re

WORK = re.compile(r'^[Ww][1-9][0-9]{0,15}$')
DOI = re.compile(r'^10\.[0-9]{4,9}/[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')


def singleton(identifier):
    """Construct a narrowly scoped work lookup without making a request."""
    if not isinstance(identifier, str) or not identifier or len(identifier) > 150 or identifier != identifier.strip():
        raise ValueError('A bounded OpenAlex work identity is required')
    if WORK.fullmatch(identifier):
        target = identifier.upper()
    elif DOI.fullmatch(identifier) and identifier.rsplit('/', 1)[1] not in ('.', '..'):
        target = 'doi:' + identifier
    else:
        raise ValueError('Unsupported OpenAlex work identity')
    return {'status': 'plan_only', 'method': 'GET', 'url': 'https://api.openalex.org/works/' + target,
            'credential_required': False, 'provider_requests': 0, 'paid_requests': 0, 'writes': 0,
            'requires_current_provider_policy_check': True, 'requires_atomic_budget_reservation': True,
            'requires_native_lease_and_private_decision_fence': True, 'publication_authorized': False}


def defer_429(headers, *, at=None):
    """Record a conservative earliest recheck; never make an automatic retry."""
    now = at or datetime.now(timezone.utc)
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None or not isinstance(headers, dict) or len(headers) > 64:
        raise ValueError('Timezone-aware rate-limit observation required')
    now = now.astimezone(timezone.utc)
    normalized = {}
    for key, value in headers.items():
        if (not isinstance(key, str) or not key or len(key) > 128 or not isinstance(value, str) or
                len(value) > 4096 or key.lower() in normalized):
            raise ValueError('Rate-limit headers invalid')
        normalized[key.lower()] = value.strip()
    candidates, incomplete = [], False
    for key in ('retry-after', 'x-ratelimit-reset'):
        value = normalized.get(key)
        if value is None:
            continue
        if re.fullmatch(r'[0-9]+', value):
            if len(value) > 8:
                return {'status': 'held', 'reason': 'provider_cooldown_requires_reconciliation',
                        'resume_not_before': None, 'automatic_retry': False, 'writes': 0}
            seconds = int(value)
            if seconds > 7*86400:
                return {'status': 'held', 'reason': 'provider_cooldown_requires_reconciliation',
                        'resume_not_before': None, 'automatic_retry': False, 'writes': 0}
            candidates.append(now + timedelta(seconds=seconds))
        elif key == 'retry-after' and len(value) <= 40:
            try:
                parsed = parsedate_to_datetime(value)
                if parsed.tzinfo is None or parsed.utcoffset() is None:
                    raise ValueError
                parsed = parsed.astimezone(timezone.utc)
                if parsed > now + timedelta(days=7):
                    return {'status': 'held', 'reason': 'provider_cooldown_requires_reconciliation',
                            'resume_not_before': None, 'automatic_retry': False, 'writes': 0}
                candidates.append(parsed)
            except (TypeError, ValueError, OverflowError):
                incomplete = True
        else:
            incomplete = True
    if incomplete:
        return {'status': 'held', 'reason': 'provider_cooldown_requires_reconciliation',
                'resume_not_before': None, 'automatic_retry': False, 'writes': 0}
    if not candidates:
        candidates.append(datetime.combine(now.date()+timedelta(days=1), datetime.min.time(), timezone.utc))
    # Even an expired or zero provider value cannot schedule an immediate retry.
    resume = max([now + timedelta(seconds=60), *candidates])
    return {'status': 'held', 'reason': 'provider_rate_limited', 'resume_not_before': resume.isoformat(),
            'automatic_retry': False, 'requires_provider_policy_recheck': True, 'writes': 0}

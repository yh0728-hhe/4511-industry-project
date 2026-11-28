"""Pure quota/rate-limit classification shared by both CLI transports.

No network, no retry, no reset/refund logic: classification only. Callers
decide how to stop; this module never calls a budget or raises itself.
"""

import re

_GUARD_SUBTYPES = frozenset(('error_max_turns','error_max_budget_usd','error_max_structured_output_retries'))

QUOTA_SUBTYPES = frozenset(('error_quota_exceeded', 'error_quota', 'quota_exceeded'))
QUOTA_TEXT_MARKERS = (
    'quota', 'usage limit', 'usage-limit', 'hit your limit', 'hit-your-limit',
    'out of usage', 'out-of-usage', 'rate limit', 'rate-limit',
    'credits required', 'credits-required',
)


def _mentions_quota(value):
    if not isinstance(value, str):
        return False
    lowered = re.sub(r'[-_]+',' ',value.lower())
    if re.search(r'\b(?:disk|storage|filesystem|file system)\s+quota\b|\benospc\b',lowered):
        return False
    quota_rejection = re.search(
        r'\b(?:quota(?:\s+(?:has\s+been|is|was))?\s+(?:exceeded|exhausted|depleted|reached)'
        r'|(?:exceeded|exhausted|insufficient)\s+(?:\w+\s+){0,2}quota'
        r'|(?:hit|reached)\s+(?:your|the)\s+quota)\b',lowered)
    return (quota_rejection is not None or
        any(marker in lowered for marker in QUOTA_TEXT_MARKERS if marker!='quota'))


def is_quota_result_envelope(envelope):
    """True only for an explicit quota/usage-limit error envelope.

    Only ever classifies when `is_error` is True; a successful envelope whose
    text happens to mention "quota" is never treated as exhaustion here, and
    generic errors (max-turns, budget-usd guard, unrelated limits) without an
    explicit quota/usage-limit signal are left unclassified.
    """
    if not isinstance(envelope, dict) or envelope.get('is_error') is not True:
        return False
    subtype=envelope.get('subtype')
    if subtype is not None and not isinstance(subtype,str):return False
    if subtype in _GUARD_SUBTYPES:
        return False
    if subtype in QUOTA_SUBTYPES:
        return True
    if _mentions_quota(envelope.get('result')):
        return True
    errors = envelope.get('errors')
    if isinstance(errors, list) and any(_mentions_quota(e) for e in errors):
        return True
    return False


def find_primary_rate_limit_rejection(events):
    """Return the first top-level `rate_limit_event` whose PRIMARY status is `rejected`.

    Only the primary `rate_limit_info.status` is consulted; a secondary/overage
    rejection reported alongside an allowed primary status is not terminal here.
    Only top-level stream events are consulted, never nested tool/source text.
    Once a primary rejection is found it is returned regardless of any later
    event reporting `allowed`; the first recorded cause is never overwritten.
    """
    for event in events:
        if not isinstance(event, dict) or event.get('type') != 'rate_limit_event':
            continue
        info = event.get('rate_limit_info')
        if isinstance(info, dict) and info.get('status') == 'rejected':
            return event
    return None

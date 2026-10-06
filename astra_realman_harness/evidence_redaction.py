"""Credential fields and validated usage counters for local evidence exports."""
import re

STATS={'input_tokens','output_tokens','total_tokens','cached_tokens','reasoning_tokens',
       'cache_read_input_tokens','cache_creation_input_tokens'}
STAT_OBJECTS={'token_usage','input_tokens_details','output_tokens_details'}


def sensitive_key(key):
    key=re.sub(r'[- ]','_',key.lower())
    if key in STATS|STAT_OBJECTS:return False
    return ('token' in key or key in {'token','authorization','proxy_authorization','password','cookie','set_cookie'}
            or key.endswith('_token') or any(x in key for x in ('authorization','api_key','apikey','secret','credential','password')))


def statistic(key,value):
    """Only recognized nonnegative integer counters survive; strings cannot masquerade as usage."""
    if value is None:return None
    if key in STATS:return value if type(value) is int and value>=0 else '[REDACTED_INVALID_STATISTIC]'
    if not isinstance(value,dict):return '[REDACTED_INVALID_STATISTIC]'
    return {k:statistic(k,v) if k in STATS|STAT_OBJECTS else '[REDACTED]' for k,v in value.items()}


def redact_fields(value):
    if isinstance(value,list):return [redact_fields(v) for v in value]
    if not isinstance(value,dict):return value
    return {k:'[REDACTED]' if sensitive_key(k) else statistic(k,v) if k in STATS|STAT_OBJECTS else redact_fields(v) for k,v in value.items()}

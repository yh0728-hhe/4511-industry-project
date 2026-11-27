"""Presentation-layer identifier tokens for model-facing JSON payloads.

These tokens are an opaque display seam, not a cryptographic privacy or
pretraining guarantee: a motivated holder of the canonical identifier can
always recompute the same token. The goal is narrower and purely practical —
keep post-cutoff canonical names/ids out of literal strings handed to the
model, without touching any other text, evidence, citations, or free-form
prose that may happen to contain the same words.
"""
import hashlib
import re

_IDENTIFIER_KEYS = ('company_id', 'subject_id')
_TOKEN_PATTERN = re.compile(r'^subject_[0-9a-f]{20}$')


def model_subject_id(primary_id, subject_id=None):
    if not isinstance(primary_id, str) or not primary_id.strip():
        raise ValueError('explicit primary identifier required')
    if subject_id is not None and (not isinstance(subject_id, str) or not subject_id.strip()):
        raise ValueError('explicit peer subject identifier required')
    actual = subject_id if subject_id is not None else primary_id
    return 'subject_' + hashlib.sha256(actual.encode('utf-8')).hexdigest()[:20]


def _present(value, primary_id):
    if isinstance(value, dict):
        copied = {}
        for key, val in value.items():
            if key in _IDENTIFIER_KEYS and isinstance(val, str) and val:
                copied[key] = val if _TOKEN_PATTERN.fullmatch(val) else model_subject_id(primary_id, val)
            else:
                copied[key] = _present(val, primary_id)
        return copied
    if isinstance(value, list):
        return [_present(item, primary_id) for item in value]
    if isinstance(value, tuple):
        return tuple(_present(item, primary_id) for item in value)
    return value


def present_payload(value, primary_id):
    if not isinstance(primary_id, str) or not primary_id.strip():
        raise ValueError('explicit primary identifier required')
    return _present(value, primary_id)


def decode_subject_id(token, primary_id, known_subjects=()):
    if token is None:
        return None
    if not isinstance(token, str):
        raise ValueError('typed token string or None required')
    if not isinstance(primary_id, str) or not primary_id.strip():
        raise ValueError('explicit primary identifier required')
    if not all(isinstance(x, str) and x.strip() for x in known_subjects):
        raise ValueError('explicit known canonical subject identifiers required')
    if not token:
        return token
    candidates = dict.fromkeys((primary_id, *known_subjects))
    for candidate in candidates:
        if model_subject_id(primary_id, candidate) == token:
            return candidate
    return token

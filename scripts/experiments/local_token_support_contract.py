"""OPTIONAL experimental guard: refuse unsupported token-level evaluations.

Purpose only: if a pretrained LettuceDetect-style token classifier is ever
reused locally, this module defines a strict contract an "infer_tokens"
callable must satisfy before any unsupported-span claim is trusted. It is
pure stdlib, performs NO model calls, HTTP, package install, training, or
Y/label edits, and is NOT wired into any production path.

Known gap, still unresolved: the actual public LettuceDetect model output
is a per-wordpiece-token classification with no character offsets into the
raw answer string. A tokenizer/offset-mapping bridge from token index to
answer character span is STILL NEEDED before any real model's output could
satisfy `infer_tokens` here. This file ships no such bridge, calls no
model, and makes no compatibility or quality claim about LettuceDetect or
any other detector.

This is not a faithfulness ratio, not a truth certification, and not a
replacement for the source admission or final claim-review gates used elsewhere.
A complete receipt means structural answer coverage only, not semantic certainty.
"""
from __future__ import annotations

_THRESHOLD = 0.5  # fixed before evaluation; never tuned per-input


def _require(condition, message):
    if not condition:
        raise ValueError(message)


def _validate_text_list(context):
    _require(isinstance(context, list) and len(context) > 0, 'CONTEXT_NONEMPTY_LIST_REQUIRED')
    for item in context:
        _require(isinstance(item, str) and item.strip(), 'CONTEXT_ITEM_NONBLANK_STRING_REQUIRED')


def _validate_nonblank_str(value, name):
    _require(isinstance(value, str) and value.strip(), name + '_NONBLANK_STRING_REQUIRED')


def _validate_positive_int(value, name):
    _require(type(value) is int and value > 0, name + '_POSITIVE_INT_REQUIRED')


def _validate_probability(value, name):
    _require(
        (type(value) is float or type(value) is int) and not isinstance(value, bool),
        name + '_NUMERIC_REQUIRED',
    )
    value = float(value)
    _require(value == value and value not in (float('inf'), float('-inf')), name + '_FINITE_REQUIRED')
    _require(0.0 <= value <= 1.0, name + '_IN_RANGE_REQUIRED')
    return value


def _validate_token_records(records, answer_len):
    _require(isinstance(records, list) and len(records) > 0, 'TOKEN_RECORDS_NONEMPTY_LIST_REQUIRED')
    parsed = []
    for record in records:
        _require(isinstance(record, dict) and set(record) == {'start', 'end', 'unsupported_probability'},
                  'TOKEN_RECORD_EXACT_KEYS_REQUIRED')
        start, end = record['start'], record['end']
        _require(type(start) is int and type(end) is int, 'TOKEN_OFFSETS_STRICT_INT_REQUIRED')
        _require(0 <= start < end <= answer_len, 'TOKEN_OFFSETS_IN_RANGE_REQUIRED')
        probability = _validate_probability(record['unsupported_probability'], 'UNSUPPORTED_PROBABILITY')
        parsed.append((start, end, probability))
    return parsed


def _covered_mask(records, answer):
    covered = [False] * len(answer)
    for start, end, _ in records:
        for i in range(start, end):
            covered[i] = True
    for i, ch in enumerate(answer):
        if not ch.isspace() and not covered[i]:
            raise ValueError('INCOMPLETE_ANSWER_COVERAGE')


def _merge_unsupported_spans(records, threshold):
    """Merge overlapping-or-touching flagged (prob >= threshold) spans.

    Rule: sort flagged (start, end) pairs by start; merge two spans when the
    next span's start is <= the current merged span's end (i.e. overlapping
    or directly adjacent with no gap). Non-overlapping, non-adjacent spans
    stay separate.
    """
    flagged = sorted((s, e) for s, e, p in records if p >= threshold)
    merged = []
    for start, end in flagged:
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def evaluate_token_support(*, context, question, answer, max_tokens, token_count, infer_tokens):
    """Preflight-guard and validate a token-level unsupported-span evaluation.

    Parameters
    ----------
    context: nonempty list of nonblank str passages.
    question: nonblank str.
    answer: nonblank str being evaluated.
    max_tokens: strict int > 0, explicit caller-supplied token budget.
    token_count: callable(context, question, answer) -> strict positive int.
        Called BEFORE infer_tokens. If it exceeds max_tokens this function
        refuses with ValueError and infer_tokens is never called -- no
        automatic truncation or chunking is performed.
    infer_tokens: callable(context, question, answer) -> nonempty list of
        dict records with exact keys {start, end, unsupported_probability}.
        start/end are strict int character offsets into `answer`
        (0 <= start < end <= len(answer)); unsupported_probability is a
        strict float/int (not bool) in [0, 1]. Every non-whitespace
        character of `answer` must be covered by at least one record's
        [start, end) range, or this function refuses.

    Returns
    -------
    A JSON-serializable dict receipt (see module docstring for scope and
    known gaps). Raises ValueError on any malformed, empty, or incomplete
    input; never invents a score by catching exceptions.
    """
    _validate_text_list(context)
    _validate_nonblank_str(question, 'QUESTION')
    _validate_nonblank_str(answer, 'ANSWER')
    _validate_positive_int(max_tokens, 'MAX_TOKENS')

    total_tokens = token_count(context, question, answer)
    _validate_positive_int(total_tokens, 'TOKEN_COUNT_RESULT')
    if total_tokens > max_tokens:
        raise ValueError('TOKEN_BUDGET_EXCEEDED_REFUSING_BEFORE_INFERENCE')

    records = infer_tokens(context, question, answer)
    parsed = _validate_token_records(records, len(answer))
    _covered_mask(parsed, answer)

    max_unsupported_probability = max(p for _, _, p in parsed)
    any_unsupported = max_unsupported_probability >= _THRESHOLD
    merged_spans = _merge_unsupported_spans(parsed, _THRESHOLD)

    return dict(
        method='token_support_diagnostic',
        complete=True,
        total_tokens=total_tokens,
        answer_token_count=len(parsed),
        max_unsupported_probability=max_unsupported_probability,
        any_unsupported=any_unsupported,
        threshold=_THRESHOLD,
        unsupported_spans=[
            dict(start=s, end=e, text=answer[s:e]) for s, e in merged_spans
        ],
        quality_accuracy_claim=False,
    )

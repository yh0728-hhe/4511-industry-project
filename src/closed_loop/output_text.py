"""Syntactic analysis-text checks only; no semantic entailment or repair."""
import json
import re


def validate_plain_analysis_text(value):
    if not isinstance(value,str) or not value.strip():
        raise ValueError('INVALID_ANALYSIS_TEXT_FORMAT')
    if re.search(r'</(?:parameter|tool_call|function_call|tool_use)(?:>|\.?)\s*$',value,re.I):
        raise ValueError('INVALID_ANALYSIS_TEXT_FORMAT')
    try:decoded=json.loads(value)
    except (ValueError,TypeError):return value
    if isinstance(decoded,(dict,list)):
        raise ValueError('INVALID_ANALYSIS_TEXT_FORMAT')
    return value

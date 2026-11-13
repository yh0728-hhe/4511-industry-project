"""Reuse a pure upstream decision node behind stable citation/revision contracts.

This is the deterministic decision-aggregation seam, not the full live committee.
No model or search client is imported or initialized here.
"""
from dataclasses import dataclass
from math import isfinite
from types import SimpleNamespace

from .contracts import Decision
from .vendor.dialectic_decision import decide_final_investment_decision


@dataclass(frozen=True)
class ScoredArgument:
    argument_type: str
    score: float
    cited_fact_ids: tuple[str,...]

    def __post_init__(self):
        if self.argument_type not in ('pro','contra'):raise ValueError('pro/contra role required')
        if type(self.score) is not int or not 14<=self.score<=98:
            raise ValueError('DIALECTIC quality total requires 14 integer criteria scored 1..7 (total 14..98)')
        if not isinstance(self.cited_fact_ids,tuple) or not self.cited_fact_ids:
            raise ValueError('each argument needs stable supporting fact IDs')


def aggregate_arguments(arguments, active_fact_ids, essential_gaps=()):
    """Preserve upstream mean-per-side aggregation; add an explicit gap exit."""
    arguments=tuple(arguments);known=frozenset(active_fact_ids)
    for argument in arguments:
        if not isinstance(argument,ScoredArgument) or not set(argument.cited_fact_ids)<=known:
            raise ValueError('argument cites unavailable/obsolete evidence')
    if essential_gaps or not arguments:return Decision.MORE_DILIGENCE
    state=SimpleNamespace(final_arguments=arguments,final_decision=None)
    result=decide_final_investment_decision(state)
    return Decision.INVEST if result.final_decision=='invest' else Decision.PASS

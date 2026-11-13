"""DIALECTIC pure binary decision node, extracted without model/search imports.

Source: https://github.com/pantageepapa/DIALECTIC/blob/dfb296ca5cb69054a289e34531df9782aa2cf4c8/src/agent/pipeline/stages/decision.py
MIT License, Copyright (c) 2024 LangChain; see LICENSE-DIALECTIC.
Only change: deferred annotations permit use without importing upstream state.
Function source/body otherwise retained verbatim. Not the whole DIALECTIC agent.
"""
from __future__ import annotations

def decide_final_investment_decision(
    state: IterativeInvestmentStoryState,
) -> IterativeInvestmentStoryState:
    """Compare pro/contra scores, make decision.

    Calculates average scores for pro and contra arguments.
    If pro average > contra average, recommend invest.
    Otherwise, recommend not_invest.
    """
    pro_final_arguments = [
        arg for arg in state.final_arguments if arg.argument_type == "pro"
    ]
    contra_final_arguments = [
        arg for arg in state.final_arguments if arg.argument_type == "contra"
    ]

    pro_final_arguments_score = (
        sum(arg.score for arg in pro_final_arguments) / len(pro_final_arguments)
        if pro_final_arguments
        else 0
    )
    contra_final_arguments_score = (
        sum(arg.score for arg in contra_final_arguments) / len(contra_final_arguments)
        if contra_final_arguments
        else 0
    )

    if pro_final_arguments_score > contra_final_arguments_score:
        state.final_decision = "invest"
    else:
        state.final_decision = "not_invest"

    return state

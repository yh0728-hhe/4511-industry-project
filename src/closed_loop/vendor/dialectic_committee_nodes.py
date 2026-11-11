"""DIALECTIC committee-stage function bodies and prompts (MIT).

Upstream commit dfb296ca5cb69054a289e34531df9782aa2cf4c8.
Copyright (c) 2024 LangChain; full license: LICENSE-DIALECTIC.
Bodies/prompts retained; import-time client setup and backoff decorators omitted.
Model access is injected by native_support and each dispatch reserves a budget.
This adapted module is not an unchanged upstream application or paper replication.
"""
from __future__ import annotations
import asyncio
from typing import Literal
from ..native_support import (
    Argument, ArgumentsOutput, ArgumentCritique, SingleArgumentScore,
    IndividualRefinedArgumentOutput, HumanMessage, SystemMessage, get_llm, llm,
)
from .dialectic_decision import decide_final_investment_decision

ARGUMENT_GENERATION_SYSTEM_PROMPT = """You are a very experienced investor at a top‑tier VC fund. You are also a great storyteller and can tell a compelling story.

"""

PRO_ARGUMENTS_USER_PROMPT = """Generate {n_pro_arguments} pro arguments why this company is a good investment opportunity.

Each argument should be concise (max. 100 words) and backed by specific data from the questions and answers.

A good argument provides a unique perspective on the investment opportunity that addresses the following criteria:
1. Local Acceptability - Are the premises believable and factually plausible given the provided Q&A facts?
2. Local Relevance - Do the premises clearly contribute to supporting or rejecting the conclusion about investment?
3. Local Sufficiency - Do the premises provide enough support to justify the conclusion?
4. Cogency - Does the argument have premises that are acceptable, relevant, and sufficient to support the investment conclusion?
5. Credibility - Does the argument make the author appear credible and trustworthy to VC investors?
6. Emotional Appeal - Does the argument create emotions that make the VC investors more receptive?
7. Clarity - Does the argument use correct and widely unambiguous language as well as avoid deviation from the issue?
8. Appropriateness - Is the style of reasoning and language suitable for a professional VC investment discussion?
9. Arrangement - Is the argument well-structured, with a logical order of premises and conclusion?
10. Effectiveness - Does the argument succeed in persuading the VC investors toward or against investing?
11. Global Acceptability - Would most VCs consider it a valid/legitimate argument?
12. Global Relevance - Does the argument meaningfully contribute to resolving the overall investment question?
13. Global Sufficiency - Does the argument adequately anticipate and rebut the main counterarguments from the argument's stance?
14. Reasonableness - Does the argument resolve the issue in a way acceptable to the VC investors, balancing global acceptability, relevance, and sufficiency?

Here are the questions and answers about the company:
{questions_and_answers}

Provide the qa_indices that were used to generate the argument but never show them in the argument text.
"""

CONTRA_ARGUMENTS_USER_PROMPT = """Generate {n_contra_arguments} contra arguments why this company is a bad investment opportunity.

Each argument should be concise (2-3 sentences) and backed by specific data from the questions and answers.
Lack of data is not a good contra argument.

A good argument provides a unique perspective on the investment opportunity that addresses the following criteria:
1. Local Acceptability - Are the premises believable and factually plausible given the provided Q&A facts?
2. Local Relevance - Do the premises clearly contribute to supporting or rejecting the conclusion about investment?
3. Local Sufficiency - Do the premises provide enough support to justify the conclusion?
4. Cogency - Does the argument have premises that are acceptable, relevant, and sufficient to support the investment conclusion?
5. Credibility - Does the argument make the author appear credible and trustworthy to VC investors?
6. Emotional Appeal - Does the argument create emotions that make the VC investors more receptive?
7. Clarity - Does the argument use correct and widely unambiguous language as well as avoid deviation from the issue?
8. Appropriateness - Is the style of reasoning and language suitable for a professional VC investment discussion?
9. Arrangement - Is the argument well-structured, with a logical order of premises and conclusion?
10. Effectiveness - Does the argument succeed in persuading the VC investors toward or against investing?
11. Global Acceptability - Would most VCs consider it a valid/legitimate argument?
12. Global Relevance - Does the argument meaningfully contribute to resolving the overall investment question?
13. Global Sufficiency - Does the argument adequately anticipate and rebut the main counterarguments from the argument's stance?
14. Reasonableness - Does the argument resolve the issue in a way acceptable to the VC investors, balancing global acceptability, relevance, and sufficiency?

Here are the questions and answers about the company:
{questions_and_answers}

Provide the qa_indices that were used to generate the argument but never show them in the argument text.
"""

DEVILS_ADVOCATE_PRO_SYSTEM_PROMPT = """You are a very experienced VC investor against investing in the company. However, your colleague thinks it is a good investment opportunity.
Your job is to criticize the pro argument given by your colleague using the questions and answers about the company and defend your position.
Be direct to persuade your colleague not to invest in the company.
"""

DEVILS_ADVOCATE_INDIVIDUAL_PRO_ARGUMENT_USER_PROMPT = """Here are the questions and answers about the company:
{questions_and_answers}

Here is the argument you have to criticize to persuade the colleague not to invest in the company:
{argument}

Keep your critique concise in 3-4 sentences.
"""

DEVILS_ADVOCATE_CONTRA_SYSTEM_PROMPT = """You are a very experienced VC investor in favor of investing in the company. However, your colleague thinks it is a bad investment opportunity.
Your job is to criticize the given contra argument given by your colleague using the questions and answers about the company and defend your position.
Be direct to persuade your colleague to invest in the company.
"""

DEVILS_ADVOCATE_INDIVIDUAL_CONTRA_ARGUMENT_USER_PROMPT = """Here are the questions and answers about the company:
{questions_and_answers}

Here is the argument you have to criticize to persuade the colleague to invest in the company:
{argument}

Keep your critique concise in 3-4 sentences.
"""

CRITERIA_MAPPING = [
    "Local Acceptability",
    "Local Relevance",
    "Local Sufficiency",
    "Cogency",
    "Credibility",
    "Emotional Appeal",
    "Clarity",
    "Appropriateness",
    "Arrangement",
    "Effectiveness",
    "Global Acceptability",
    "Global Relevance",
    "Global Sufficiency",
    "Reasonableness",
]

SINGLE_ARGUMENT_EVALUATION_SYSTEM_PROMPT = """You are an impartial LLM judge to evaluate the quality of an argument in the VC investment context. The goal of the argument is to support or reject a startup investment decision in a persuasive way.
The quality of an argument in the venture capital investment context should be evaluated along the following 14 dimensions. For each dimension, assign a score from 1 (Low) to 7 (High), and provide a short feedback (1 sentence) how to improve the score.

14 Dimensions:
1. Local Acceptability - Are the premises believable and factually plausible given the provided Q&A facts?
2. Local Relevance - Do the premises clearly contribute to supporting or rejecting the conclusion about investment?
3. Local Sufficiency - Do the premises provide enough support to justify the conclusion?
4. Cogency - Does the argument have premises that are acceptable, relevant, and sufficient to support the investment conclusion?
5. Credibility - Does the argument make the author appear credible and trustworthy to VC investors?
6. Emotional Appeal - Does the argument create emotions that make the VC investors more receptive?
7. Clarity - Does the argument use correct and widely unambiguous language as well as avoid deviation from the issue?
8. Appropriateness - Is the style of reasoning and language suitable for a professional VC investment discussion?
9. Arrangement - Is the argument well-structured, with a logical order of premises and conclusion?
10. Effectiveness - Does the argument succeed in persuading the VC investors toward or against investing?
11. Global Acceptability - Would most VCs consider it a valid/legitimate argument?
12. Global Relevance - Does the argument meaningfully contribute to resolving the overall investment question?
13. Global Sufficiency - Does the argument adequately anticipate and rebut the main counterarguments from the argument's stance?
14. Reasonableness - Does the argument resolve the issue in a way acceptable to the VC investors, balancing global acceptability, relevance, and sufficiency?
"""

EVALUATE_SINGLE_ARGUMENT_USER_PROMPT = """Argument to evaluate:
{argument}
{critique}
"""

REFINE_PRO_ARGUMENT_SYSTEM_PROMPT = """You are a very experienced investor at a top‑tier VC fund. You are sure that the company is a good investment opportunity.
Your job is to revise your argument to reach better argument quality scores.
"""

REFINE_CONTRA_ARGUMENT_SYSTEM_PROMPT = """You are a very experienced investor at a top‑tier VC fund. You are sure that the company is a bad investment opportunity.
Your job is to revise your argument to reach better argument quality scores.
"""

REFINE_PRO_ARGUMENTS_USER_PROMPT = """Here are the Q&A facts about the company:
{questions_and_answers}

Here is your previous argument:
{argument}

Here are the argument quality scores (1-7) to your previous argument:
{argument_feedback}

Refine your argument by improving argument quality scores.

Output format:
{{
    "refined_argument": "Refined Argument without qa_indices (one paragraph in max. 2 sentences)",
    "qa_indices": "List of indices referencing which questions and answers from the provided Q&A pairs were used to support this argument"
}}
"""

REFINE_CONTRA_ARGUMENTS_USER_PROMPT = """Here are the Q&A facts about the company:
{questions_and_answers}

Here are the argument quality scores (1-7) to your previous argument:
{argument_feedback}

Here is your previous argument:
{argument}

Refine your argument by improving argument quality scores.

Output format:
{{
    "refined_argument": "Refined Argument without qa_indices (one paragraph in max. 2 sentences)",
    "qa_indices": "List of indices referencing which questions and answers from the provided Q&A pairs were used to support this argument"
}}
"""

def format_qa_pairs_with_index(qa_pairs: list[dict[str, str]]) -> str:
    """
    Format a list of question/answer pairs into a string with index.
    """
    return "\n".join(
        [f"{i}: {qa['question']}\n{qa['answer']}" for i, qa in enumerate(qa_pairs)]
    )

def format_qa_pairs_without_index(qa_pairs: list[dict[str, str]]) -> str:
    """
    Format a list of question/answer pairs into a string without index.
    """
    return "\n".join([f"{qa['question']}\n{qa['answer']}" for qa in qa_pairs])

def generate_context_block(qa_pairs: list[dict[str, str]], vc_context: str) -> str:
    """Generate a context block from Q&A pairs and VC context.

    This formats Q&A pairs and VC context into a readable string
    for inclusion in LLM prompts.

    Args:
        qa_pairs: List of question/answer dictionaries
        vc_context: Additional VC-specific context

    Returns:
        Formatted context block string
    """
    if qa_pairs:
        formatted_pairs = "\n-----------------\n".join(
            [f"Q: {qa['question']}\nA: {qa['answer']}" for qa in qa_pairs]
        )
        context_block = f"\nSub questions and answers:\n{formatted_pairs}"
    else:
        context_block = ""

    if vc_context:
        context_block += f"\n\nVC Context:\n{vc_context}"

    return context_block

def convert_llm_arguments_to_objects(
    llm_arguments: list[ArgumentOutput],
    argument_type: Literal["pro", "contra"],
    tracking_id_counter: int = 1,
) -> tuple[list[Argument], int]:
    """Convert LLM output arguments to Argument dataclass instances.

    Args:
        llm_arguments: List of ArgumentOutput from the LLM
        argument_type: Whether these are "pro" or "contra" arguments
        tracking_id_counter: Starting counter for tracking IDs

    Returns:
        Tuple of (list of Argument objects, next tracking_id_counter)
    """
    arguments = []
    for arg_data in llm_arguments:
        argument = Argument(
            content=arg_data.content,
            argument_type=argument_type,
            qa_indices=arg_data.qa_indices,
            tracking_id=f"arg_{tracking_id_counter}",
        )
        arguments.append(argument)
        tracking_id_counter += 1
    return arguments, tracking_id_counter

def format_argument_feedback(argument_scores: list[CriterionScore]) -> str:
    """Format argument feedback scores into readable text.

    Args:
        argument_scores: List of CriterionScore for each of the 14 criteria

    Returns:
        Formatted string with each criterion, its reasoning, and score
    """
    formatted_feedback_list = []
    for i, feedback in enumerate(argument_scores):
        formatted_feedback_list.append(
            f"{CRITERIA_MAPPING[i]}: {feedback.reasoning} (Score: {feedback.score})"
        )
    return "\n".join(formatted_feedback_list)

def check_if_final(
    state: IterativeInvestmentStoryState,
) -> Literal["score_and_select_best_k", "generate_pro_and_contra_arguments"]:
    """Router: determines entry point based on is_final flag.

    If is_final is True, skip generation and go straight to scoring.
    This is used when we already have arguments and just want to
    run the final evaluation.
    """
    if state.is_final:
        if len(state.current_arguments) == 0:
            raise ValueError("No current arguments to prepare final arguments")
        return "score_and_select_best_k"
    return "generate_pro_and_contra_arguments"

def generate_pro_and_contra_arguments(
    state: IterativeInvestmentStoryState,
) -> IterativeInvestmentStoryState:
    """Helper node that routes to parallel pro/contra generation."""
    return state

def generate_pro_arguments(
    state: IterativeInvestmentStoryState,
) -> dict:
    """Generate N pro arguments from Q&A pairs.

    Only runs in iteration 0 - subsequent iterations use refined
    arguments from previous iterations.

    Returns dict with pro_arguments to update state.
    """
    if state.current_iteration > 0:
        return state

    # Use all_qa_pairs from the answering stage
    qa_pairs = state.all_qa_pairs
    formatted_qa_pairs = format_qa_pairs_with_index(qa_pairs)

    llm_with_structured_output = llm.with_structured_output(ArgumentsOutput)
    arguments: ArgumentsOutput = llm_with_structured_output.invoke(
        [
            SystemMessage(content=ARGUMENT_GENERATION_SYSTEM_PROMPT),
            HumanMessage(
                content=PRO_ARGUMENTS_USER_PROMPT.format(
                    n_pro_arguments=state.config.n_pro_arguments,
                    questions_and_answers=formatted_qa_pairs,
                )
            ),
        ]
    )

    pro_argument_objects, _ = convert_llm_arguments_to_objects(
        arguments.arguments, "pro", tracking_id_counter=1
    )

    # Attach Q&A pairs to each argument using indices
    for arg in pro_argument_objects:
        arg.qa_pairs = [
            qa_pairs[index]
            for index in arg.qa_indices
            if index < len(qa_pairs)
        ]

    return {"pro_arguments": pro_argument_objects}

def generate_contra_arguments(
    state: IterativeInvestmentStoryState,
) -> dict:
    """Generate N contra arguments from Q&A pairs.

    Only runs in iteration 0 - subsequent iterations use refined
    arguments from previous iterations.

    Returns dict with contra_arguments to update state.
    """
    if state.current_iteration > 0:
        return state

    # Use all_qa_pairs from the answering stage
    qa_pairs = state.all_qa_pairs
    formatted_qa_pairs = format_qa_pairs_with_index(qa_pairs)

    llm_with_structured_output = llm.with_structured_output(ArgumentsOutput)
    arguments: ArgumentsOutput = llm_with_structured_output.invoke(
        [
            SystemMessage(content=ARGUMENT_GENERATION_SYSTEM_PROMPT),
            HumanMessage(
                content=CONTRA_ARGUMENTS_USER_PROMPT.format(
                    n_contra_arguments=state.config.n_contra_arguments,
                    questions_and_answers=formatted_qa_pairs,
                )
            ),
        ]
    )

    # Start counter after pro arguments
    pro_args_count = len(state.pro_arguments) if state.pro_arguments else 0
    contra_argument_objects, _ = convert_llm_arguments_to_objects(
        arguments.arguments, "contra", tracking_id_counter=pro_args_count + 1
    )

    # Attach Q&A pairs to each argument using indices
    for arg in contra_argument_objects:
        arg.qa_pairs = [
            qa_pairs[index]
            for index in arg.qa_indices
            if index < len(qa_pairs)
        ]

    return {"contra_arguments": contra_argument_objects}

def merge_arguments(
    state: IterativeInvestmentStoryState,
) -> dict:
    """Combine pro and contra into current_arguments.

    This merges the separately generated arguments into a single
    list for the next stage of processing.
    """
    return {"current_arguments": state.pro_arguments + state.contra_arguments}

async def _apply_devils_advocate_to_pro_argument(
    argument: Argument, qa_pairs_formatted: str, former_critique: str | None = None
) -> Argument:
    """Critique a single pro argument from the opposing perspective.

    The critique comes from someone against investing, challenging
    the reasons why this would be a good investment.
    """
    llm_with_structured_output = llm.with_structured_output(ArgumentCritique)

    user_prompt = DEVILS_ADVOCATE_INDIVIDUAL_PRO_ARGUMENT_USER_PROMPT.format(
        questions_and_answers=qa_pairs_formatted, argument=argument.content
    )
    if former_critique:
        user_prompt += f"\nHere is your past critique - do not repeat the same critique but find a new one:\n{former_critique}"

    critique: ArgumentCritique = await llm_with_structured_output.ainvoke(
        [
            SystemMessage(content=DEVILS_ADVOCATE_PRO_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]
    )
    argument.critique = critique.critique
    return argument

async def _apply_devils_advocate_to_contra_argument(
    argument: Argument, qa_pairs_formatted: str, former_critique: str | None = None
) -> Argument:
    """Critique a single contra argument from the opposing perspective.

    The critique comes from someone in favor of investing, challenging
    the reasons why this would be a bad investment.
    """
    llm_with_structured_output = llm.with_structured_output(ArgumentCritique)

    user_prompt = DEVILS_ADVOCATE_INDIVIDUAL_CONTRA_ARGUMENT_USER_PROMPT.format(
        questions_and_answers=qa_pairs_formatted, argument=argument.content
    )
    if former_critique:
        user_prompt += f"\nHere is your past critique - do not repeat the same critique but find a new one:\n{former_critique}"

    critique: ArgumentCritique = await llm_with_structured_output.ainvoke(
        [
            SystemMessage(content=DEVILS_ADVOCATE_CONTRA_SYSTEM_PROMPT),
            HumanMessage(content=user_prompt),
        ]
    )
    argument.critique = critique.critique
    return argument

def apply_devils_advocate(
    state: IterativeInvestmentStoryState,
) -> IterativeInvestmentStoryState:
    """Helper node that routes to parallel pro/contra critique."""
    return state

async def apply_devils_advocate_to_pro_arguments(
    state: IterativeInvestmentStoryState,
) -> dict:
    """Apply critiques to all pro arguments in parallel.

    Uses asyncio.gather for concurrent execution, significantly
    speeding up the critique phase.
    """
    if not state.current_arguments:
        raise ValueError("No current arguments to apply devil's advocate to")

    # Use all_qa_pairs from the answering stage
    formatted_qa_pairs = format_qa_pairs_without_index(state.all_qa_pairs)

    pro_arguments = [
        arg for arg in state.current_arguments if arg.argument_type == "pro"
    ]
    if len(pro_arguments) == 0:
        return {"devils_advocate_pro_arguments": []}

    critique_tasks = [
        _apply_devils_advocate_to_pro_argument(
            arg, formatted_qa_pairs, arg.former_critique
        )
        for arg in pro_arguments
    ]

    critiqued_arguments = await asyncio.gather(*critique_tasks)

    return {"devils_advocate_pro_arguments": critiqued_arguments}

async def apply_devils_advocate_to_contra_arguments(
    state: IterativeInvestmentStoryState,
) -> dict:
    """Apply critiques to all contra arguments in parallel.

    Uses asyncio.gather for concurrent execution, significantly
    speeding up the critique phase.
    """
    if not state.current_arguments:
        raise ValueError("No current arguments to apply devil's advocate to")

    # Use all_qa_pairs from the answering stage
    formatted_qa_pairs = format_qa_pairs_without_index(state.all_qa_pairs)

    contra_arguments = [
        arg for arg in state.current_arguments if arg.argument_type == "contra"
    ]
    if len(contra_arguments) == 0:
        return {"devils_advocate_contra_arguments": []}

    critique_tasks = [
        _apply_devils_advocate_to_contra_argument(
            arg, formatted_qa_pairs, arg.former_critique
        )
        for arg in contra_arguments
    ]

    critiqued_arguments = await asyncio.gather(*critique_tasks)

    return {"devils_advocate_contra_arguments": critiqued_arguments}

async def score_single_argument(argument: Argument) -> Argument:
    """Score one argument against all 14 criteria.

    Uses temperature=0.0 for consistent, reproducible scoring.
    Includes retry logic to ensure we get exactly 14 scores.
    """
    llm = get_llm(temperature=0.0)
    llm_with_structured_output = llm.with_structured_output(SingleArgumentScore)

    system_prompt = SINGLE_ARGUMENT_EVALUATION_SYSTEM_PROMPT
    critique = (
        "Critique of the argument: " + argument.critique if argument.critique else ""
    )

    # Retry logic for getting correct number of scores
    max_retries = 5
    score = None
    for attempt in range(max_retries):
        score = await llm_with_structured_output.ainvoke(
            [
                SystemMessage(content=system_prompt),
                HumanMessage(
                    content=EVALUATE_SINGLE_ARGUMENT_USER_PROMPT.format(
                        argument=argument.content, critique=critique
                    )
                ),
            ]
        )

        if len(score.scores) == len(CRITERIA_MAPPING):
            break
        elif attempt < max_retries - 1:
            print(
                f"Attempt {attempt + 1}: Got {len(score.scores)} scores instead of {len(CRITERIA_MAPPING)}, retrying..."
            )
        else:
            raise ValueError(
                f"After {max_retries} attempts, still got {len(score.scores)} scores instead of {len(CRITERIA_MAPPING)}"
            )

    argument.score = sum(criterion.score for criterion in score.scores)
    argument.argument_feedback = format_argument_feedback(score.scores)
    return argument

async def score_arguments_in_parallel(arguments: list[Argument]) -> list[Argument]:
    """Score multiple arguments concurrently.

    Uses asyncio.gather for parallel execution, significantly
    speeding up the evaluation phase.
    """
    if not arguments:
        return []

    tasks = [score_single_argument(argument) for argument in arguments]
    scored_arguments = await asyncio.gather(*tasks)

    return scored_arguments

async def score_and_select_best_k(
    state: IterativeInvestmentStoryState,
) -> dict:
    """Score all arguments, select top K for refinement.

    Scores all current arguments individually, then selects the
    top K based on the current iteration's k_best setting.

    Returns both the full scored list and the selected subset.
    """
    arguments_to_score = state.current_arguments
    scored_arguments = await score_arguments_in_parallel(arguments_to_score)

    # Sort and select top K for current iteration
    k_best = state.get_current_k_best()
    top_arguments = sorted(scored_arguments, key=lambda x: x.score, reverse=True)[
        :k_best
    ]

    return {
        "current_arguments": scored_arguments,
        "selected_arguments": top_arguments,
    }

async def _refine_individual_pro_argument(
    argument: Argument, qa_pairs_formatted: str
) -> IndividualRefinedArgumentOutput:
    """Refine a single pro argument using its critique and feedback.

    Uses the argument's feedback scores to guide improvement,
    focusing on low-scoring criteria.
    """
    llm_with_structured_output = llm.with_structured_output(
        IndividualRefinedArgumentOutput
    )

    refined_argument: IndividualRefinedArgumentOutput = (
        await llm_with_structured_output.ainvoke(
            [
                SystemMessage(content=REFINE_PRO_ARGUMENT_SYSTEM_PROMPT),
                HumanMessage(
                    content=REFINE_PRO_ARGUMENTS_USER_PROMPT.format(
                        argument=argument.content,
                        argument_feedback=argument.argument_feedback,
                        questions_and_answers=qa_pairs_formatted,
                    )
                ),
            ]
        )
    )

    return refined_argument

async def _refine_individual_contra_argument(
    argument: Argument, qa_pairs_formatted: str
) -> IndividualRefinedArgumentOutput:
    """Refine a single contra argument using its critique and feedback.

    Uses the argument's feedback scores to guide improvement,
    focusing on low-scoring criteria.
    """
    llm_with_structured_output = llm.with_structured_output(
        IndividualRefinedArgumentOutput
    )

    refined_argument: IndividualRefinedArgumentOutput = (
        await llm_with_structured_output.ainvoke(
            [
                SystemMessage(content=REFINE_CONTRA_ARGUMENT_SYSTEM_PROMPT),
                HumanMessage(
                    content=REFINE_CONTRA_ARGUMENTS_USER_PROMPT.format(
                        argument=argument.content,
                        argument_feedback=argument.argument_feedback,
                        questions_and_answers=qa_pairs_formatted,
                    )
                ),
            ]
        )
    )

    return refined_argument

async def refine_pro_arguments(
    state: IterativeInvestmentStoryState,
) -> dict:
    """Refine all selected pro arguments in parallel.

    Only refines arguments that were selected in the previous
    evaluation stage (the top K).
    """
    pro_arguments_with_critiques: list[Argument] = [
        arg for arg in state.selected_arguments if arg.argument_type == "pro"
    ]

    if len(pro_arguments_with_critiques) == 0:
        return {"refined_pro_arguments": []}

    # Use all_qa_pairs from the answering stage
    qa_pairs = state.all_qa_pairs
    formatted_qa_pairs = format_qa_pairs_with_index(qa_pairs)

    refinement_tasks = [
        _refine_individual_pro_argument(arg, formatted_qa_pairs)
        for arg in pro_arguments_with_critiques
    ]

    refined_results = await asyncio.gather(*refinement_tasks)

    # Update arguments with refined content
    for arg, refined_result in zip(pro_arguments_with_critiques, refined_results):
        arg.refined_content = refined_result.content
        arg.refined_qa_indices = refined_result.qa_indices
        arg.qa_pairs = [
            qa_pairs[index]
            for index in arg.refined_qa_indices
            if index < len(qa_pairs)
        ]

    return {"refined_pro_arguments": pro_arguments_with_critiques}

async def refine_contra_arguments(
    state: IterativeInvestmentStoryState,
) -> dict:
    """Refine all selected contra arguments in parallel.

    Only refines arguments that were selected in the previous
    evaluation stage (the top K).
    """
    contra_arguments_with_critiques: list[Argument] = [
        arg for arg in state.selected_arguments if arg.argument_type == "contra"
    ]

    if len(contra_arguments_with_critiques) == 0:
        return {"refined_contra_arguments": []}

    # Use all_qa_pairs from the answering stage
    qa_pairs = state.all_qa_pairs
    formatted_qa_pairs = format_qa_pairs_with_index(qa_pairs)

    refinement_tasks = [
        _refine_individual_contra_argument(arg, formatted_qa_pairs)
        for arg in contra_arguments_with_critiques
    ]

    refined_results = await asyncio.gather(*refinement_tasks)

    # Update arguments with refined content
    for arg, refined_result in zip(contra_arguments_with_critiques, refined_results):
        arg.refined_content = refined_result.content
        arg.refined_qa_indices = refined_result.qa_indices
        arg.qa_pairs = [
            qa_pairs[index]
            for index in arg.refined_qa_indices
            if index < len(qa_pairs)
        ]

    return {"refined_contra_arguments": contra_arguments_with_critiques}

def merge_refined_arguments(
    state: IterativeInvestmentStoryState,
) -> dict:
    """Combine refined pro and contra arguments.

    Merges the separately refined arguments into a single list
    for history tracking and iteration management.
    """
    return {
        "refined_arguments": state.refined_pro_arguments + state.refined_contra_arguments
    }

def add_arguments_to_history(
    state: IterativeInvestmentStoryState,
) -> IterativeInvestmentStoryState:
    """Track iteration state in history.

    Saves a snapshot of the current iteration's arguments for
    later analysis and debugging.
    """
    state.arguments_history.append(
        {
            "iteration": state.current_iteration,
            "refined_arguments": state.refined_arguments,
            "selected_arguments": state.selected_arguments,
            "pro_arguments": state.pro_arguments,
            "contra_arguments": state.contra_arguments,
            "devils_advocate_pro_arguments": state.devils_advocate_pro_arguments,
            "devils_advocate_contra_arguments": state.devils_advocate_contra_arguments,
            "refined_pro_arguments": state.refined_pro_arguments,
            "refined_contra_arguments": state.refined_contra_arguments,
        }
    )

    return state

def reset_arguments_and_increment_iteration(
    state: IterativeInvestmentStoryState,
) -> IterativeInvestmentStoryState:
    """Prepare for next iteration cycle.

    Converts refined arguments to new current arguments,
    preserving tracking IDs and critique history.
    """
    new_current_arguments = []
    for refined_arg in state.refined_arguments:
        new_arg = Argument(
            # refined_content becomes content
            content=refined_arg.refined_content,
            qa_indices=refined_arg.refined_qa_indices,
            argument_type=refined_arg.argument_type,
            score=refined_arg.score,
            qa_pairs=refined_arg.qa_pairs,
            # Add former critique to the argument
            former_critique=refined_arg.critique,
            # Preserve tracking_id across iterations
            tracking_id=refined_arg.tracking_id,
        )
        new_current_arguments.append(new_arg)

    state.current_arguments = new_current_arguments

    # Reset other arguments to empty lists
    state.refined_arguments = []
    state.selected_arguments = []
    state.pro_arguments = []
    state.contra_arguments = []
    state.devils_advocate_pro_arguments = []
    state.devils_advocate_contra_arguments = []
    state.refined_pro_arguments = []
    state.refined_contra_arguments = []

    # Increment iteration
    state.current_iteration += 1

    return state

def check_continue(
    state: IterativeInvestmentStoryState,
) -> Literal["apply_devils_advocate", "prepare_final_arguments"]:
    """Router: continue iterating or finalize.

    Checks if we've reached max_iterations. If so, proceeds to
    final argument preparation. Otherwise, continues the loop.
    """
    if not state.should_continue_iterations:
        return "prepare_final_arguments"
    return "apply_devils_advocate"

async def prepare_final_arguments(
    state: IterativeInvestmentStoryState,
) -> IterativeInvestmentStoryState:
    """Score the final set of arguments.

    Performs one final scoring of all remaining arguments
    before making the investment decision.
    """
    state.final_arguments = state.current_arguments

    # Score the final arguments
    scored_arguments = await score_arguments_in_parallel(state.final_arguments)
    state.arguments_history.append(
        {
            "iteration": state.current_iteration,
            "selected_arguments": scored_arguments,
            "refined_arguments": scored_arguments,
        }
    )

    return state

def create_final_investment_story(
    state: IterativeInvestmentStoryState,
) -> IterativeInvestmentStoryState:
    """Finalize the investment story state.

    Currently a no-op since we don't generate investment proposals.
    The state already contains all necessary final data.
    """
    return state

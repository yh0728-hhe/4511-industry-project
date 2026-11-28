"""Reuse of one Open Deep Research *research role prompt pattern*, not the
upstream framework.

Attribution: adapted from the "research" role's human-researcher instructions
in langchain-ai/open_deep_research, commit 1b7d2e80db9faa586165c60e09096dbbfd483a64
(see data/metadata/workflow_20261121/odr_reuse_source_20261124.json and
src/closed_loop/vendor/LICENSE-ODR). Only the verbatim five-step <Instructions>
text below is reused; upstream tool names (tavily_search/think_tool), its
wall-clock "today's date" framing and its tool-call budget numbers are NOT
reused. This module does not execute, install or vendor upstream code, and
nothing here reproduces or certifies upstream's actual research quality -- it
is a prompt/workflow-pattern reuse only, adapted for bounded historical-only
link navigation over an existing, already-tested MeteredResearchProvider.
No new search engine, tool-calling loop or model client is introduced.
"""
from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
from types import SimpleNamespace

from .guards import BudgetStopped
from .native_support import HumanMessage, NativeBinding, get_llm
from .research_backend import MeteredResearchProvider

# Verbatim inner <Instructions> body from the pinned upstream research-role
# prompt (research_system_prompt.txt lines 17-25), excluding upstream's
# <Task>/<Available Tools>/<Hard Limits>/<Show Your Thinking> sections, its
# tool names and its wall-clock "today's date" framing.
ODR_UPSTREAM_FIVE_STEPS = (
    'Think like a human researcher with limited time. Follow these steps:\n'
    '\n'
    '1. **Read the question carefully** - What specific information does the user need?\n'
    '2. **Start with broader searches** - Use broad, comprehensive queries first\n'
    '3. **After each search, pause and assess** - Do I have enough to answer? What\'s still missing?\n'
    '4. **Execute narrower searches as you gather information** - Fill in the gaps\n'
    '5. **Stop when you can answer confidently** - Don\'t keep searching for perfection'
)

ODR_ADAPTATION_NOTE = (
    'Adaptation for bounded historical link navigation (not the upstream search-tool loop):\n'
    '- "Start with broader searches" here means the initial broad inspection of the '
    'subject\'s already-admitted historical sources already performed by this run\'s '
    'bootstrap fetch; you do not call it again.\n'
    '- "Execute narrower searches" here means: FETCH exactly one path already present '
    'in historical_link_hints below, or STOP. There is no live web, search engine, or '
    'tool-calling capability, and no think_tool; do not request any tool call.\n'
    '- Use the fixed historical cutoff supplied as `cutoff` '
    'below; it is not the wall-clock date and must not be treated as such.\n'
    '- "Stop when you can answer confidently" here also means: stop immediately when no '
    'further permitted lead would add anything new. Unknowns that remain unresolved stay '
    'unknown; do not fill them from memory or by guessing.\n'
    '- Do not infer the content of a hinted link from its label, URL or position; a link '
    'proves only that it was observed, never its target content.\n'
    'Return action FETCH with exactly one listed source_path, or STOP with source_path null. '
    'reason is a short justification for that one choice, not private deliberation. '
    'missing_information lists short open questions that remain unanswered; it does not '
    'invent facts.'
)

ODR_SCHEMA_TAG = 'odr_navigation_plan_v1:action,source_path,reason,missing_information'
ODR_PROMPT_VERSION = 'odr-research-role-reuse-v1'
_MAX_MISSING_INFORMATION = 8
_MAX_INSTRUCTION_TEXT_BYTES = 4000


def odr_prompt_fingerprint():
    """Fingerprint ties the own prompt build to the real upstream text actually
    reused here plus this module's adaptation note and schema, so a label-only
    version bump cannot stale-cache a changed prompt."""
    payload = dict(upstream=ODR_UPSTREAM_FIVE_STEPS, adaptation=ODR_ADAPTATION_NOTE, schema=ODR_SCHEMA_TAG)
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()


@dataclass
class ODRNavigationPlan:
    action: str
    source_path: str | None
    reason: str
    missing_information: list[str]


class ODRResearchProvider(MeteredResearchProvider):
    """Same bootstrap -> plan -> fetch -> verify loop as MeteredResearchProvider;
    only ``_plan`` is overridden to use the ODR-derived instruction/schema.

    All search/fetch/source-gate/budget/stop behaviour (``search``, ``_fetch``,
    ``_safe_hints``, ``link_hints``) is the parent's actual tested logic,
    unchanged. This class adds no new model client, tool or search engine.
    """

    @property
    def cache_namespace(self):
        return ODR_PROMPT_VERSION+':'+odr_prompt_fingerprint()

    def _plan(self, task, hints):
        subject = task.subject_id or task.company_id
        facts = tuple(fact for (owner, _), fact in sorted(self._admitted.items()) if owner == subject)
        rows = tuple(dict(question=task.question, answer=fact.text, fact_id=fact.fact_id,
                          source_id=fact.source_id, subject_id=fact.company_id, url=fact.url,
                          available_by=fact.availability_upper_bound.isoformat(),
                          reliability=fact.proof_kind) for fact in facts)
        view = SimpleNamespace(company_id=self.request.company.company_id,
                               mandate=self.request.mandate, as_of=self.request.as_of.isoformat(),
                               fact_revision=len(facts), argument_revision=0, qa_pairs=rows)
        binding = NativeBinding(self.backend, self.call_budget, view)
        instruction_text = ODR_UPSTREAM_FIVE_STEPS + '\n\n' + ODR_ADAPTATION_NOTE
        if len(instruction_text.encode('utf-8')) > _MAX_INSTRUCTION_TEXT_BYTES:
            raise BudgetStopped('ODR_INSTRUCTION_TEXT_TOO_LARGE')
        payload = dict(
            task=dict(role=task.role, question=task.question, subject_id=subject),
            historical_link_hints=list(hints),
            cutoff=self.request.as_of.isoformat(),
            instruction=instruction_text,
            prompt_bundle=dict(version=ODR_PROMPT_VERSION, fingerprint=odr_prompt_fingerprint()))
        try:
            with binding.activate():
                plan = get_llm(temperature=0).with_structured_output(ODRNavigationPlan).invoke(
                    [HumanMessage(json.dumps(payload, sort_keys=True))])
        finally:
            self.last_calls.extend(binding.calls)
        self._validate_plan(plan, hints)
        citations = sorted(fact.fact_id for (owner, _), fact in self._admitted.items() if owner == subject)
        self.trace.append(dict(event='ODR_RESEARCH_PLAN', action=plan.action, reason=plan.reason,
                               missing_information=list(plan.missing_information), citations=citations))
        if plan.action == 'STOP':
            return None
        return plan.source_path

    @staticmethod
    def _validate_plan(plan, hints):
        if not isinstance(plan, ODRNavigationPlan):
            raise BudgetStopped('ODR_PLAN_SCHEMA_INVALID')
        if plan.action not in ('FETCH', 'STOP'):
            raise BudgetStopped('ODR_PLAN_SCHEMA_INVALID')
        if not isinstance(plan.reason, str) or not plan.reason.strip():
            raise BudgetStopped('ODR_PLAN_SCHEMA_INVALID')
        if (not isinstance(plan.missing_information, list) or
                len(plan.missing_information) > _MAX_MISSING_INFORMATION or
                not all(isinstance(item, str) and item.strip() for item in plan.missing_information)):
            raise BudgetStopped('ODR_PLAN_SCHEMA_INVALID')
        total_bytes = len(plan.reason.encode('utf-8')) + sum(
            len(item.encode('utf-8')) for item in plan.missing_information)
        if total_bytes > _MAX_INSTRUCTION_TEXT_BYTES:
            raise BudgetStopped('ODR_PLAN_TEXT_TOO_LARGE')
        if plan.action == 'STOP':
            if plan.source_path is not None:
                raise BudgetStopped('ODR_PLAN_SCHEMA_INVALID')
            return
        if (not isinstance(plan.source_path, str) or
                plan.source_path not in {hint['path'] for hint in hints}):
            raise BudgetStopped('RESEARCH_PLAN_NOT_OBSERVED')

"""Bounded model-selected navigation over verified historical website links.

No search engine, credential loader, current profile or outcome-file tool is
available here. Retrieval and proof production remain in the trusted archive
provider. The model selects an observed path; its output is never evidence.
"""
from dataclasses import dataclass
from datetime import datetime
import json
from types import SimpleNamespace
from urllib.parse import urlparse

from .contracts import CompanySeed, ResearchRequest, aware
from .agent_prompts import RESEARCH_NAVIGATION_INSTRUCTION
from .guards import BudgetStopped
from .native_support import HumanMessage, NativeBinding, get_llm


@dataclass
class ResearchNavigationPlan:
    action: str
    source_path: str | None


class MeteredResearchProvider:
    """Provider-compatible archive bootstrap -> plan -> fetch -> verify loop.

    ``backend`` is the same explicitly supplied backend as the lead/committee;
    physical live calls retain its spend-envelope accounting. Fixture backends
    consume logical model reservations only. ``archive_provider`` must be a
    trusted verifier with the same request, gateway and per-run HTTP budget.
    """
    controls_historical_navigation = True

    def __init__(self, request, gateway, budget, backend, archive_provider,
                 max_navigation_steps=2):
        if backend is None:
            raise ValueError('explicit research model backend required')
        if gateway.request != request or budget.bound_request != request:
            raise ValueError('request/gateway/budget contexts must match')
        if (archive_provider.request != request or archive_provider.gateway is not gateway
                or archive_provider.call_budget is not budget):
            raise ValueError('archive provider must share request/gateway/budget')
        if getattr(backend, 'call_budget', budget) is not budget:
            raise ValueError('model backend must share call budget')
        if type(max_navigation_steps) is not int or not 1 <= max_navigation_steps <= 8:
            raise ValueError('navigation step cap must be an integer from 1 to 8')
        self.request = request
        self.gateway = gateway
        self.call_budget = budget
        self.backend = backend
        self.archive_provider = archive_provider
        self.max_navigation_steps = max_navigation_steps
        self.trace = []
        self.last_calls = []
        self._admitted = {}

    @property
    def receipts(self):
        return self.archive_provider.receipts

    @property
    def attempts(self):
        return self.archive_provider.attempts

    def _safe_hints(self, subject):
        domain = self.archive_provider.domain_anchors.get(subject)
        if domain is None:
            return ()
        allowed_sources = {source_id for (owner, source_id) in self._admitted if owner == subject}
        safe = {}
        for hint in self.archive_provider.link_hints():
            if not isinstance(hint, dict):
                continue
            try:
                if (hint['subject_id'] != subject or
                        hint['found_in_source_id'] not in allowed_sources or
                        hint['target_content_verified'] is not False or
                        aware(datetime.fromisoformat(hint['observed_at'])) > self.request.as_of):
                    continue
                path = hint['path']
                # Reuse the task contract's path validation; URL origin is checked
                # independently instead of trusting a model-supplied path or date.
                ResearchRequest('research', 'historical navigation', self.request.company.company_id,
                                subject, path)
                parsed = urlparse(hint['url'])
                if (parsed.scheme not in ('http', 'https') or parsed.username is not None or
                        parsed.password is not None or parsed.port not in (None, 80, 443) or
                        (parsed.hostname or '').lower().removeprefix('www.') != domain.removeprefix('www.') or
                        (parsed.path or '/') + ('?' + parsed.query if parsed.query else '') != path):
                    continue
                label = hint['label']
                if not isinstance(label, str) or len(label) > 160:
                    continue
                safe[path] = dict(subject_id=subject, url=hint['url'], path=path, label=label,
                                  observed_at=hint['observed_at'],
                                  found_in_source_id=hint['found_in_source_id'],
                                  target_content_verified=False)
            except (KeyError, TypeError, ValueError):
                continue
        return tuple(safe[path] for path in sorted(safe))[:16]

    def link_hints(self):
        """Expose only hints discovered in already admitted historical sources."""
        hints = []
        for subject in sorted(self.archive_provider.domain_anchors):
            hints.extend(self._safe_hints(subject))
        return tuple(hints[:16])

    def _fetch(self, task, found):
        for candidate in self.archive_provider.search(task):
            fact, rejection = self.gateway.admit(candidate, task.subject_id)
            if fact is None:
                self.trace.append(dict(event='RESEARCH_SOURCE_HELD', **rejection))
                continue
            self._admitted[(fact.company_id, fact.source_id)] = fact
            found[(fact.company_id, fact.source_id, fact.topic)] = candidate
        self.call_budget.check()

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
        instruction = dict(
            task=dict(role=task.role, question=task.question, subject_id=subject),
            historical_link_hints=list(hints),
            instruction=RESEARCH_NAVIGATION_INSTRUCTION)
        try:
            with binding.activate():
                plan = get_llm(temperature=0).with_structured_output(ResearchNavigationPlan).invoke(
                    [HumanMessage(json.dumps(instruction, sort_keys=True))])
        finally:
            self.last_calls.extend(binding.calls)
        if plan.action == 'STOP' and plan.source_path is None:
            return None
        if (plan.action != 'FETCH' or not isinstance(plan.source_path, str) or
                plan.source_path not in {hint['path'] for hint in hints}):
            raise BudgetStopped('RESEARCH_PLAN_NOT_OBSERVED')
        return plan.source_path

    def search(self, task):
        if not isinstance(task, ResearchRequest) or task.company_id != self.request.company.company_id:
            raise ValueError('research task must match run company')
        self.call_budget.check()
        subject = task.subject_id or task.company_id
        domain = self.archive_provider.domain_anchors.get(subject)
        if domain is None:
            self.trace.append(dict(event='RESEARCH_STOP', reason='SUBJECT_DOMAIN_UNRESOLVED'))
            return ()
        CompanySeed(subject, subject, domain)
        found = {}
        self.last_calls = []
        visited = set()
        if task.source_path is not None:
            visited.add(task.source_path)
        try:
            self._fetch(task, found)
            for receipt in self.receipts:
                if (receipt.get('subject_id') == subject and
                        (subject, receipt.get('source_id')) in self._admitted):
                    parsed = urlparse(receipt['original_url'])
                    visited.add((parsed.path or '/') + ('?' + parsed.query if parsed.query else ''))
            for _ in range(self.max_navigation_steps):
                hints = tuple(hint for hint in self._safe_hints(subject)
                              if hint['path'] not in visited and hint['path'] != '/')
                if not hints:
                    self.trace.append(dict(event='RESEARCH_STOP', reason='NO_UNVISITED_HISTORICAL_LINKS'))
                    break
                # Each fresh target needs both an index and a replay request.
                remaining = self.call_budget.caps['search'] - self.call_budget.used['search']
                physical_remaining = (self.archive_provider.max_requests
                                      - self.archive_provider._request_count)
                if remaining < 2 or physical_remaining < 2:
                    self.trace.append(dict(event='RESEARCH_STOP', reason='INSUFFICIENT_HTTP_BUDGET'))
                    break
                path = self._plan(task, hints)
                if path is None:
                    self.trace.append(dict(event='RESEARCH_STOP', reason='MODEL_STOP'))
                    break
                visited.add(path)
                before = len(found)
                self._fetch(ResearchRequest(task.role, task.question, task.company_id, task.subject_id, path), found)
                self.trace.append(dict(event='RESEARCH_NAVIGATED', subject_id=subject,
                                       source_path=path, new_sources=len(found)-before))
            else:
                self.trace.append(dict(event='RESEARCH_STOP', reason='NAVIGATION_STEP_CAP'))
        except BudgetStopped as exc:
            # Preserve earlier admitted evidence, but a provider/metering/schema
            # failure is terminal for this run: no later stage may spend again.
            self.call_budget.stop(str(exc))
            self.trace.append(dict(event='RESEARCH_STOP', reason=str(exc)))
        return tuple(found[key] for key in sorted(found))

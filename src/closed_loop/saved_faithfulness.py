"""Optional post-hoc Ragas-style faithfulness check on a saved rationale.

Never re-runs the saved DIALECTIC proposal and never edits the original run.
Only the saved `rationale` text is assessed against the admitted_fact_ids the
proposal itself cites; `thesis`, `essential_gaps` and the draft trace stay
unreviewed. The caller-supplied `view` is trusted input, not independently
authenticated here -- the hash checks below only detect post-hoc
inconsistency between the saved run and that view, not forged provenance.
A supported score here is not model accuracy and not an investment gate.
"""
import hashlib
import json
from pathlib import Path
from datetime import datetime
from .contracts import aware

from .analysis_acceptance import build_analysis_review_packet
from .guards import BudgetStopped
from .saved_analysis_review import FINAL_KEYS, _load

QUESTION = 'Is the saved investment rationale supported by its cited historical evidence?'
UNREVIEWED_FIELDS = ('thesis', 'essential_gaps', 'draft_trace')
_ERR = 'INVALID_SAVED_FAITHFULNESS_INPUT'


def _digest_text(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def _view_payload(view):
    return dict(company_id=view.company_id, mandate=view.mandate, as_of=view.as_of,
        fact_revision=view.fact_revision, argument_revision=view.argument_revision,
        qa_pairs=[dict(row) for row in view.qa_pairs])


def assess_saved_rationale(run_dir, output_dir, *, view, checker, proposal_name='proposal.json'):
    """Write a new rationale-only faithfulness artifact outside the original run.

    Supports only the existing single-source package_runner plan/proposal
    shape. Rejects any mismatch (fingerprint, company/as_of/mandate, source
    hash, foreign fact IDs, output collision) before any model call. Legacy
    `result.json` must be explicitly requested; there is no automatic
    fallback and no automatic retry on a BudgetStopped failure.
    """
    try:
        if proposal_name not in ('proposal.json', 'result.json'):
            raise ValueError(_ERR)
        source = Path(run_dir).resolve(strict=True)
        target = Path(output_dir).resolve()
        if target == source or source in target.parents or target.exists():
            raise ValueError(_ERR)

        plan, plan_sha = _load(source / 'plan.json')
        fingerprint = plan.get('fingerprint')
        canonical = {k: v for k, v in plan.items() if k != 'fingerprint'}
        expected = _digest_text(json.dumps(canonical, sort_keys=True))
        if fingerprint != expected or plan.get('status') != 'SOURCE_ADMITTED_BEFORE_MODEL_CONSTRUCTION':
            raise ValueError(_ERR)

        source_id = plan.get('source_id')
        source_sha256 = plan.get('source_sha256')
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValueError(_ERR)
        if not isinstance(source_sha256, str) or not source_sha256.strip():
            raise ValueError(_ERR)

        checker.call_budget.check()
        req = checker.call_budget.bound_request
        company = plan.get('company')
        if not isinstance(company, dict):
            raise ValueError(_ERR)
        company_id = company.get('company_id')
        if company_id != view.company_id or company_id != req.company.company_id:
            raise ValueError(_ERR)
        if plan.get('as_of') != view.as_of or plan.get('as_of') != req.as_of.isoformat():
            raise ValueError(_ERR)
        if plan.get('mandate') != view.mandate or plan.get('mandate') != req.mandate:
            raise ValueError(_ERR)

        proposal, proposal_sha = _load(source / proposal_name)
        if 'proposed_decision' in proposal or any(k not in proposal for k in FINAL_KEYS):
            raise ValueError(_ERR)
        final_packet = {k: proposal[k] for k in FINAL_KEYS}
        packet = build_analysis_review_packet(final_packet, fingerprint)
        admitted = packet['admitted_fact_ids']
        if not admitted or len(set(admitted)) != len(admitted):
            raise ValueError(_ERR)

        rows = list(view.qa_pairs)
        view_fact_ids = [row['fact_id'] for row in rows]
        if len(set(view_fact_ids)) != len(view_fact_ids) or set(view_fact_ids) != set(admitted):
            raise ValueError(_ERR)
        for row in rows:
            available=aware(datetime.fromisoformat(row['available_by']))
            if available > req.as_of:
                raise ValueError(_ERR)
            if row.get('source_id') != source_id:
                raise ValueError(_ERR)
            if _digest_text(row['answer']) != source_sha256:
                raise ValueError(_ERR)

        input_sha256 = dict(plan=plan_sha, proposal=proposal_sha,
            view=_digest_text(json.dumps(_view_payload(view), sort_keys=True)))
    except (ValueError, KeyError, TypeError, OSError, UnicodeError):
        raise ValueError(_ERR) from None

    target.mkdir(parents=True, exist_ok=False)
    intent = dict(status='SAVED_RATIONALE_FAITHFULNESS_PRE_DISPATCH',
        intent='Assess only the saved rationale text against its own admitted_fact_ids; '
            'not a thesis/essential_gaps review and not an investment decision.',
        question=QUESTION, proposal_source=proposal_name,
        legacy_source_explicit=proposal_name == 'result.json',
        input_sha256=input_sha256, original_run_modified=False)
    (target / 'intent.json').write_text(json.dumps(intent, indent=2) + '\n', encoding='utf-8')

    try:
        assessment = checker.assess(view, question=QUESTION, response=final_packet['rationale'],
            cited_fact_ids=list(admitted))
    except BudgetStopped as exc:
        failure = dict(status='SAVED_RATIONALE_FAITHFULNESS_FAILED', reason=str(exc),
            input_sha256=input_sha256, original_run_modified=False, human_review=False,
            semantic_support_certified=False, unreviewed=list(UNREVIEWED_FIELDS),
            diagnostic_trace=getattr(checker,'last_trace',[]))
        (target / 'faithfulness_result.json').write_text(json.dumps(failure, indent=2) + '\n', encoding='utf-8')
        raise

    report = dict(status='SAVED_RATIONALE_FAITHFULNESS_WRITTEN', automatic_diagnostics=assessment,
        input_sha256=input_sha256, original_run_modified=False, human_review=False,
        semantic_support_certified=False, unreviewed=list(UNREVIEWED_FIELDS))
    (target / 'faithfulness_result.json').write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
    return report

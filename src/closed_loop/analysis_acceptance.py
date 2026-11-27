"""Gate a research-analysis result before it can release a non-diligence decision.

This module never certifies truth. It only (a) builds a deterministic,
exhaustive claim inventory covering every final-output textual field of an
explicit five-field analysis packet (not draft traces or transport metadata) so that no claim can be hand-picked for review, and (b) consults an
independently supplied claim-review verdict set (see claim_review.py) before
conditionally releasing the analysis's own proposed decision. The released
decision is never an "INVEST"/"PASS" label invented here, and it is never an
automatic entailment or predictive-accuracy judgment -- it is a conditional
statement that a reviewer claimed every generated claim is supported by
admitted facts.
"""

import hashlib
import json

from closed_loop.claim_review import summarize_claim_review
from .output_text import validate_plain_analysis_text

_ERR = "INVALID_ANALYSIS_PACKET"
_DECISIONS = ("INVEST", "PASS", "MORE_DILIGENCE")
_RESULT_KEYS = {
    "decision",
    "rationale",
    "admitted_fact_ids",
    "essential_gaps",
    "thesis",
}
_THESIS_KEYS = {
    "summary",
    "pro_case",
    "con_case",
    "uncertainty_notes",
    "decision_changing_questions",
    "next_checks",
    "cited_fact_ids",
}
_THESIS_LIST_KEYS = (
    "pro_case",
    "con_case",
    "uncertainty_notes",
    "decision_changing_questions",
    "next_checks",
)


def _nonempty_str(x):
    return isinstance(x, str) and bool(x.strip())


def _str_list(x):
    return isinstance(x, list) and all(isinstance(i, str) and bool(i.strip()) for i in x)


def _sha256(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _validate_result(result):
    if not isinstance(result, dict) or set(result.keys()) != _RESULT_KEYS:
        raise ValueError
    if result["decision"] not in _DECISIONS:
        raise ValueError
    if not _nonempty_str(result["rationale"]):
        raise ValueError

    admitted = result["admitted_fact_ids"]
    if not isinstance(admitted, list):
        raise ValueError
    if not all(_nonempty_str(f) for f in admitted):
        raise ValueError
    if len(set(admitted)) != len(admitted):
        raise ValueError
    admitted_set = set(admitted)
    if not admitted and result["decision"] != "MORE_DILIGENCE":
        raise ValueError

    gaps = result["essential_gaps"]
    if not isinstance(gaps, list):
        raise ValueError
    if not all(_nonempty_str(g) for g in gaps):
        raise ValueError

    thesis = result["thesis"]
    if thesis is not None:
        if not isinstance(thesis, dict) or set(thesis.keys()) != _THESIS_KEYS:
            raise ValueError
        if not _nonempty_str(thesis["summary"]):
            raise ValueError
        for k in _THESIS_LIST_KEYS:
            if not _str_list(thesis[k]):
                raise ValueError
        cited = thesis["cited_fact_ids"]
        if not _str_list(cited):
            raise ValueError
        if len(set(cited)) != len(cited):
            raise ValueError
        if not set(cited).issubset(admitted_set):
            raise ValueError
        if len(cited) == 0:
            raise ValueError

    texts=[result['rationale'],*gaps]
    if thesis is not None:
        texts.append(thesis['summary'])
        for key in _THESIS_LIST_KEYS:texts.extend(thesis[key])
    for text in texts:validate_plain_analysis_text(text)
    return admitted_set


def build_analysis_review_packet(result, run_fingerprint):
    try:
        if not _nonempty_str(run_fingerprint):
            raise ValueError
        admitted_set = _validate_result(result)
        admitted_list = list(result["admitted_fact_ids"])

        thesis = result["thesis"]
        thesis_citations = list(thesis["cited_fact_ids"]) if thesis is not None else []
        non_thesis_citations = list(admitted_list)

        claims = []

        claims.append(
            {
                "claim_id": "rationale",
                "text": result["rationale"],
                "cited_fact_ids": non_thesis_citations,
            }
        )

        for idx, gap in enumerate(result["essential_gaps"]):
            claims.append(
                {
                    "claim_id": "essential_gaps/{}".format(idx),
                    "text": gap,
                    "cited_fact_ids": non_thesis_citations,
                }
            )

        if thesis is not None:
            claims.append(
                {
                    "claim_id": "thesis.summary",
                    "text": thesis["summary"],
                    "cited_fact_ids": thesis_citations,
                }
            )
            for key in _THESIS_LIST_KEYS:
                for idx, text in enumerate(thesis[key]):
                    claims.append(
                        {
                            "claim_id": "thesis.{}/{}".format(key, idx),
                            "text": text,
                            "cited_fact_ids": thesis_citations,
                        }
                    )

        canonical = {
            "source_run_fingerprint": run_fingerprint,
            "decision": result["decision"],
            "rationale": result["rationale"],
            "essential_gaps": list(result["essential_gaps"]),
            "thesis": thesis,
            "admitted_fact_ids": admitted_list,
        }
        analysis_sha256 = _sha256(
            json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        )
        bound_run_fingerprint = _sha256(run_fingerprint + ":" + analysis_sha256)

        return {
            "source_run_fingerprint": run_fingerprint,
            "analysis_sha256": analysis_sha256,
            "run_fingerprint": bound_run_fingerprint,
            "proposed_decision": result["decision"],
            "has_thesis": thesis is not None,
            "essential_gaps": list(result["essential_gaps"]),
            "admitted_fact_ids": admitted_list,
            "claims": claims,
        }
    except ValueError:
        raise ValueError(_ERR) from None
    except Exception:
        raise ValueError(_ERR) from None


def gate_analysis(result, run_fingerprint, review=None):
    try:
        packet = build_analysis_review_packet(result, run_fingerprint)
    except ValueError:
        return {
            "proposed_decision": None,
            "decision": "MORE_DILIGENCE",
            "acceptance_state": "INVALID_ANALYSIS_PACKET",
            "semantic_support_certified": False,
        }

    proposed = packet["proposed_decision"]
    out = {
        "proposed_decision": proposed,
        "decision": "MORE_DILIGENCE",
        "semantic_support_certified": False,
        "packet": packet,
    }

    if proposed == "MORE_DILIGENCE":
        out["acceptance_state"] = "NO_SUBSTANTIVE_PROPOSAL"
        return out

    if not packet["has_thesis"]:
        out["acceptance_state"] = "MISSING_THESIS"
        return out

    if review is None:
        out["acceptance_state"] = "NOT_REVIEWED"
        return out

    try:
        review_summary = summarize_claim_review(
            run_fingerprint=packet["run_fingerprint"],
            claims=packet["claims"],
            admitted_fact_ids=packet["admitted_fact_ids"],
            review=review,
        )
    except ValueError:
        out["acceptance_state"] = "INVALID_REVIEW"
        return out

    out["review_summary"] = review_summary

    if review_summary["status"] != "SUPPORTED_BY_SUPPLIED_REVIEW":
        out["acceptance_state"] = "REQUIRES_DILIGENCE"
        return out

    if len(packet["essential_gaps"]) > 0:
        out["acceptance_state"] = "REQUIRES_DILIGENCE"
        return out

    out["decision"] = proposed
    out["acceptance_state"] = "SUPPORTED_BY_SUPPLIED_REVIEW"
    return out

"""Validate independently supplied claim-review annotations.

This module does NOT perform automatic entailment checking. It only checks
that a separately supplied human/tool review is internally consistent with
the claims and admitted facts it refers to. The supplied reviewer
annotations (verdicts, rationales) can themselves be wrong: a claim marked
SUPPORTED here only means the reviewer cited an admitted fact, not that the
citation actually entails the claim text. The returned status is therefore
conditional on the honesty/correctness of the supplied review, and is never
an independently certified truth about the claims.
"""

import hashlib

_ERR = "INVALID_CLAIM_REVIEW"
_VERDICTS = ("SUPPORTED", "UNSUPPORTED", "UNRESOLVED")
_CLAIM_KEYS = {"claim_id", "text", "cited_fact_ids"}
_REVIEW_KEYS = {"run_fingerprint", "reviewer_id", "items"}
_ITEM_KEYS = {"claim_id", "claim_sha256", "cited_fact_ids", "verdict", "rationale"}


def _nonempty_str(x):
    return isinstance(x, str) and bool(x.strip())


def _is_collection_not_str(x):
    return isinstance(x, (list, tuple, set)) and not isinstance(x, str)


def summarize_claim_review(*, run_fingerprint, claims, admitted_fact_ids, review):
    try:
        if not _nonempty_str(run_fingerprint):
            raise ValueError
        if not _is_collection_not_str(admitted_fact_ids):
            raise ValueError
        admitted_list = list(admitted_fact_ids)
        if not all(_nonempty_str(f) for f in admitted_list):
            raise ValueError
        if len(set(admitted_list)) != len(admitted_list):
            raise ValueError
        admitted_set = set(admitted_list)

        if not isinstance(claims, list) or len(claims) == 0:
            raise ValueError

        claim_ids = []
        claim_by_id = {}
        for c in claims:
            if not isinstance(c, dict) or set(c.keys()) != _CLAIM_KEYS:
                raise ValueError
            cid, text, cited = c["claim_id"], c["text"], c["cited_fact_ids"]
            if not _nonempty_str(cid) or not _nonempty_str(text):
                raise ValueError
            if not isinstance(cited, list):
                raise ValueError
            if not all(_nonempty_str(f) for f in cited):
                raise ValueError
            if len(set(cited)) != len(cited):
                raise ValueError
            if not set(cited).issubset(admitted_set):
                raise ValueError
            claim_ids.append(cid)
            claim_by_id[cid] = c

        if len(set(claim_ids)) != len(claim_ids):
            raise ValueError

        if not isinstance(review, dict) or set(review.keys()) != _REVIEW_KEYS:
            raise ValueError
        if review["run_fingerprint"] != run_fingerprint:
            raise ValueError
        if not _nonempty_str(review["reviewer_id"]):
            raise ValueError

        items = review["items"]
        if not isinstance(items, list):
            raise ValueError

        seen_claim_ids = set()
        counts = {"SUPPORTED": 0, "UNSUPPORTED": 0, "UNRESOLVED": 0}
        unsupported_ids = []
        unresolved_ids = []

        for item in items:
            if not isinstance(item, dict) or set(item.keys()) != _ITEM_KEYS:
                raise ValueError
            cid = item["claim_id"]
            if cid not in claim_by_id:
                raise ValueError
            if cid in seen_claim_ids:
                raise ValueError
            seen_claim_ids.add(cid)

            reviewed_citations = item["cited_fact_ids"]
            if not isinstance(reviewed_citations, list):
                raise ValueError
            if reviewed_citations != claim_by_id[cid]["cited_fact_ids"]:
                raise ValueError
            claim_sha256 = item["claim_sha256"]
            verdict = item["verdict"]
            rationale = item["rationale"]

            if not _nonempty_str(claim_sha256) or not _nonempty_str(rationale):
                raise ValueError
            if verdict not in _VERDICTS:
                raise ValueError

            expected_sha = hashlib.sha256(
                claim_by_id[cid]["text"].encode("utf-8")
            ).hexdigest()
            if claim_sha256 != expected_sha:
                raise ValueError

            if verdict == "SUPPORTED" and len(claim_by_id[cid]["cited_fact_ids"]) == 0:
                raise ValueError

            counts[verdict] += 1
            if verdict == "UNSUPPORTED":
                unsupported_ids.append(cid)
            elif verdict == "UNRESOLVED":
                unresolved_ids.append(cid)

        if seen_claim_ids != set(claim_ids):
            raise ValueError

        status = (
            "SUPPORTED_BY_SUPPLIED_REVIEW"
            if counts["SUPPORTED"] == len(claim_ids)
            else "REQUIRES_DILIGENCE"
        )

        return {
            "status": status,
            "reviewer_id": review["reviewer_id"],
            "run_fingerprint": run_fingerprint,
            "claim_count": len(claim_ids),
            "counts": counts,
            "unsupported_claim_ids": unsupported_ids,
            "unresolved_claim_ids": unresolved_ids,
            "semantic_support_certified": False,
            "automatic_entailment_check": False,
        }
    except ValueError:
        raise ValueError(_ERR) from None
    except Exception:
        raise ValueError(_ERR) from None

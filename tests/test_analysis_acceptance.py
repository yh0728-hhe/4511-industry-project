import copy
import hashlib
import unittest

from closed_loop.analysis_acceptance import build_analysis_review_packet, gate_analysis

FP = "src-run-fp-1"
FACTS = ["fact-1", "fact-2", "fact-3"]


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_result(decision="INVEST", with_thesis=True, gaps=None):
    thesis = None
    if with_thesis:
        thesis = {
            "summary": "Strong unit economics and defensible moat.",
            "pro_case": ["Revenue growing 3x YoY."],
            "con_case": ["Customer concentration risk."],
            "uncertainty_notes": ["Churn data incomplete."],
            "decision_changing_questions": ["What is Q4 churn?"],
            "next_checks": ["Request Q4 cohort data."],
            "cited_fact_ids": ["fact-1", "fact-2"],
        }
    return {
        "decision": decision,
        "rationale": "Based on available facts, this looks promising.",
        "admitted_fact_ids": list(FACTS),
        "essential_gaps": list(gaps) if gaps is not None else [],
        "thesis": thesis,
    }


def make_full_review(packet, verdict="SUPPORTED"):
    items = []
    for c in packet["claims"]:
        items.append(
            {
                "claim_id": c["claim_id"],
                "claim_sha256": sha(c["text"]),
                "cited_fact_ids": list(c["cited_fact_ids"]),
                "verdict": verdict,
                "rationale": "reviewed",
            }
        )
    return {
        "run_fingerprint": packet["run_fingerprint"],
        "reviewer_id": "reviewer-1",
        "items": items,
    }


class TestAnalysisAcceptance(unittest.TestCase):
    def test_no_source_more_diligence_remains_unknown(self):
        result=make_result(decision="MORE_DILIGENCE",with_thesis=False)
        result["admitted_fact_ids"]=[]
        out=gate_analysis(result,FP)
        self.assertEqual(out["acceptance_state"],"NO_SUBSTANTIVE_PROPOSAL")
        self.assertEqual(out["decision"],"MORE_DILIGENCE")

    def test_pass_is_also_blocked_until_complete_review(self):
        result=make_result(decision="PASS")
        self.assertEqual(gate_analysis(result,FP)["decision"],"MORE_DILIGENCE")
        packet=build_analysis_review_packet(result,FP)
        out=gate_analysis(result,FP,review=make_full_review(packet))
        self.assertEqual(out["decision"],"PASS")
        self.assertFalse(out["semantic_support_certified"])

    def test_no_review_blocked(self):
        result = make_result()
        out = gate_analysis(result, FP)
        self.assertEqual(out["acceptance_state"], "NOT_REVIEWED")
        self.assertEqual(out["decision"], "MORE_DILIGENCE")
        self.assertEqual(out["proposed_decision"], "INVEST")
        self.assertFalse(out["semantic_support_certified"])

    def test_complete_supported_review_releases_conditionally(self):
        result = make_result()
        packet = build_analysis_review_packet(result, FP)
        review = make_full_review(packet, "SUPPORTED")
        out = gate_analysis(result, FP, review=review)
        self.assertEqual(out["acceptance_state"], "SUPPORTED_BY_SUPPLIED_REVIEW")
        self.assertEqual(out["decision"], "INVEST")
        self.assertFalse(out["semantic_support_certified"])

    def test_unsupported_blocks(self):
        result = make_result()
        packet = build_analysis_review_packet(result, FP)
        review = make_full_review(packet, "SUPPORTED")
        review["items"][0]["verdict"] = "UNSUPPORTED"
        out = gate_analysis(result, FP, review=review)
        self.assertEqual(out["acceptance_state"], "REQUIRES_DILIGENCE")
        self.assertEqual(out["decision"], "MORE_DILIGENCE")

    def test_unresolved_blocks(self):
        result = make_result()
        packet = build_analysis_review_packet(result, FP)
        review = make_full_review(packet, "SUPPORTED")
        review["items"][0]["verdict"] = "UNRESOLVED"
        out = gate_analysis(result, FP, review=review)
        self.assertEqual(out["acceptance_state"], "REQUIRES_DILIGENCE")

    def test_missing_review_item_invalid(self):
        result = make_result()
        packet = build_analysis_review_packet(result, FP)
        review = make_full_review(packet, "SUPPORTED")
        review["items"].pop()
        out = gate_analysis(result, FP, review=review)
        self.assertEqual(out["acceptance_state"], "INVALID_REVIEW")
        self.assertEqual(out["decision"], "MORE_DILIGENCE")

    def test_extra_review_item_invalid(self):
        result = make_result()
        packet = build_analysis_review_packet(result, FP)
        review = make_full_review(packet, "SUPPORTED")
        extra = dict(review["items"][0])
        extra["claim_id"] = "bogus"
        review["items"].append(extra)
        out = gate_analysis(result, FP, review=review)
        self.assertEqual(out["acceptance_state"], "INVALID_REVIEW")

    def test_changed_body_invalidates_review(self):
        result = make_result()
        packet = build_analysis_review_packet(result, FP)
        review = make_full_review(packet, "SUPPORTED")
        result["rationale"] = result["rationale"] + " Changed."
        out = gate_analysis(result, FP, review=review)
        self.assertEqual(out["acceptance_state"], "INVALID_REVIEW")

    def test_changed_citations_invalidates_review(self):
        result = make_result()
        packet = build_analysis_review_packet(result, FP)
        review = make_full_review(packet, "SUPPORTED")
        result["thesis"]["cited_fact_ids"] = ["fact-3"]
        out = gate_analysis(result, FP, review=review)
        self.assertEqual(out["acceptance_state"], "INVALID_REVIEW")

    def test_changed_run_fingerprint_invalidates_review(self):
        result = make_result()
        packet = build_analysis_review_packet(result, FP)
        review = make_full_review(packet, "SUPPORTED")
        out = gate_analysis(result, "other-fp", review=review)
        self.assertEqual(out["acceptance_state"], "INVALID_REVIEW")

    def test_missing_thesis_for_invest_blocks(self):
        result = make_result(with_thesis=False)
        out = gate_analysis(result, FP)
        self.assertEqual(out["acceptance_state"], "MISSING_THESIS")
        self.assertEqual(out["decision"], "MORE_DILIGENCE")

    def test_essential_gaps_block_even_if_supported(self):
        result = make_result(gaps=["Need legal review."])
        packet = build_analysis_review_packet(result, FP)
        review = make_full_review(packet, "SUPPORTED")
        out = gate_analysis(result, FP, review=review)
        self.assertEqual(out["acceptance_state"], "REQUIRES_DILIGENCE")
        self.assertEqual(out["decision"], "MORE_DILIGENCE")

    def test_more_diligence_proposal_stays_unknown(self):
        result = make_result(decision="MORE_DILIGENCE", with_thesis=False)
        out = gate_analysis(result, FP)
        self.assertEqual(out["acceptance_state"], "NO_SUBSTANTIVE_PROPOSAL")
        self.assertEqual(out["decision"], "MORE_DILIGENCE")
        self.assertEqual(out["proposed_decision"], "MORE_DILIGENCE")

    def test_no_mutation_of_input(self):
        result = make_result()
        before = copy.deepcopy(result)
        packet = build_analysis_review_packet(result, FP)
        review = make_full_review(packet, "SUPPORTED")
        gate_analysis(result, FP, review=review)
        self.assertEqual(result, before)

    def test_malformed_packet_fails_closed(self):
        result = make_result()
        del result["rationale"]
        out = gate_analysis(result, FP)
        self.assertEqual(out["acceptance_state"], "INVALID_ANALYSIS_PACKET")
        self.assertEqual(out["decision"], "MORE_DILIGENCE")
        self.assertIsNone(out["proposed_decision"])

    def test_claims_exhaustively_cover_all_text_fields(self):
        result = make_result(gaps=["Gap A", "Gap B"])
        packet = build_analysis_review_packet(result, FP)
        claim_ids = {c["claim_id"] for c in packet["claims"]}
        expected = {
            "rationale",
            "essential_gaps/0",
            "essential_gaps/1",
            "thesis.summary",
            "thesis.pro_case/0",
            "thesis.con_case/0",
            "thesis.uncertainty_notes/0",
            "thesis.decision_changing_questions/0",
            "thesis.next_checks/0",
        }
        self.assertEqual(claim_ids, expected)

    def test_duplicate_admitted_fact_ids_invalid(self):
        result = make_result()
        result["admitted_fact_ids"] = ["fact-1", "fact-1"]
        with self.assertRaises(ValueError):
            build_analysis_review_packet(result, FP)

    def test_thesis_citation_not_subset_invalid(self):
        result = make_result()
        result["thesis"]["cited_fact_ids"] = ["unknown-fact"]
        with self.assertRaises(ValueError):
            build_analysis_review_packet(result, FP)

    def test_thesis_empty_citations_invalid(self):
        result = make_result()
        result["thesis"]["cited_fact_ids"] = []
        with self.assertRaises(ValueError):
            build_analysis_review_packet(result, FP)

    def test_empty_string_text_invalid(self):
        result = make_result()
        result["rationale"] = ""
        with self.assertRaises(ValueError):
            build_analysis_review_packet(result, FP)

    def test_unknown_thesis_key_invalid(self):
        result = make_result()
        result["thesis"]["extra"] = "nope"
        with self.assertRaises(ValueError):
            build_analysis_review_packet(result, FP)


if __name__ == "__main__":
    unittest.main()

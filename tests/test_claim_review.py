import hashlib
import unittest

from closed_loop.claim_review import summarize_claim_review

FP = "run-fp-abc123"
FACTS = ["fact-1", "fact-2"]


def sha(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def make_claims():
    return [
        {"claim_id": "c1", "text": "The sky is blue.", "cited_fact_ids": ["fact-1"]},
        {"claim_id": "c2", "text": "Water is wet.", "cited_fact_ids": ["fact-2"]},
    ]


def make_items(verdicts):
    claims = make_claims()
    items = []
    for c, v in zip(claims, verdicts):
        items.append(
            {
                "claim_id": c["claim_id"],
                "claim_sha256": sha(c["text"]),
                "cited_fact_ids": list(c["cited_fact_ids"]),
                "verdict": v,
                "rationale": "because reasons",
            }
        )
    return items


def make_review(verdicts, fp=FP, reviewer="rev-1"):
    return {"run_fingerprint": fp, "reviewer_id": reviewer, "items": make_items(verdicts)}


class TestClaimReview(unittest.TestCase):
    def test_changed_citation_requires_new_review(self):
        claims = make_claims()
        review = make_review(["SUPPORTED", "SUPPORTED"])
        claims[0]["cited_fact_ids"] = ["fact-2"]
        with self.assertRaises(ValueError):
            summarize_claim_review(run_fingerprint=FP, claims=claims,
                admitted_fact_ids=FACTS, review=review)

    def test_whitespace_identity_is_invalid(self):
        review = make_review(["SUPPORTED", "SUPPORTED"], reviewer="   ")
        with self.assertRaises(ValueError):
            summarize_claim_review(run_fingerprint=FP, claims=make_claims(),
                admitted_fact_ids=FACTS, review=review)

    def test_same_text_in_different_stages_can_be_reviewed_separately(self):
        claims = make_claims(); claims[1]["text"] = claims[0]["text"]
        review = make_review(["SUPPORTED", "SUPPORTED"])
        review["items"][1]["claim_sha256"] = sha(claims[1]["text"])
        result = summarize_claim_review(run_fingerprint=FP, claims=claims,
            admitted_fact_ids=FACTS, review=review)
        self.assertEqual(result["claim_count"], 2)

    def test_all_supported(self):
        out = summarize_claim_review(
            run_fingerprint=FP,
            claims=make_claims(),
            admitted_fact_ids=FACTS,
            review=make_review(["SUPPORTED", "SUPPORTED"]),
        )
        self.assertEqual(out["status"], "SUPPORTED_BY_SUPPLIED_REVIEW")
        self.assertEqual(out["counts"]["SUPPORTED"], 2)
        self.assertFalse(out["semantic_support_certified"])
        self.assertFalse(out["automatic_entailment_check"])

    def test_unsupported_blocks_status(self):
        out = summarize_claim_review(
            run_fingerprint=FP,
            claims=make_claims(),
            admitted_fact_ids=FACTS,
            review=make_review(["SUPPORTED", "UNSUPPORTED"]),
        )
        self.assertEqual(out["status"], "REQUIRES_DILIGENCE")
        self.assertEqual(out["unsupported_claim_ids"], ["c2"])

    def test_unresolved_blocks_status(self):
        out = summarize_claim_review(
            run_fingerprint=FP,
            claims=make_claims(),
            admitted_fact_ids=FACTS,
            review=make_review(["SUPPORTED", "UNRESOLVED"]),
        )
        self.assertEqual(out["status"], "REQUIRES_DILIGENCE")
        self.assertEqual(out["unresolved_claim_ids"], ["c2"])

    def test_stale_run_fingerprint(self):
        with self.assertRaises(ValueError) as ctx:
            summarize_claim_review(
                run_fingerprint=FP,
                claims=make_claims(),
                admitted_fact_ids=FACTS,
                review=make_review(["SUPPORTED", "SUPPORTED"], fp="other-run"),
            )
        self.assertEqual(str(ctx.exception), "INVALID_CLAIM_REVIEW")

    def test_edited_claim_body_hash_mismatch(self):
        claims = make_claims()
        review = make_review(["SUPPORTED", "SUPPORTED"])
        claims[0]["text"] = "The sky is green."
        with self.assertRaises(ValueError):
            summarize_claim_review(
                run_fingerprint=FP,
                claims=claims,
                admitted_fact_ids=FACTS,
                review=review,
            )

    def test_duplicate_review_item(self):
        review = make_review(["SUPPORTED", "SUPPORTED"])
        review["items"].append(review["items"][0])
        with self.assertRaises(ValueError):
            summarize_claim_review(
                run_fingerprint=FP,
                claims=make_claims(),
                admitted_fact_ids=FACTS,
                review=review,
            )

    def test_missing_review_item(self):
        review = make_review(["SUPPORTED", "SUPPORTED"])
        review["items"].pop()
        with self.assertRaises(ValueError):
            summarize_claim_review(
                run_fingerprint=FP,
                claims=make_claims(),
                admitted_fact_ids=FACTS,
                review=review,
            )

    def test_extra_review_item(self):
        review = make_review(["SUPPORTED", "SUPPORTED"])
        extra = dict(review["items"][0])
        extra["claim_id"] = "c3"
        review["items"].append(extra)
        with self.assertRaises(ValueError):
            summarize_claim_review(
                run_fingerprint=FP,
                claims=make_claims(),
                admitted_fact_ids=FACTS,
                review=review,
            )

    def test_unavailable_citation(self):
        claims = make_claims()
        claims[0]["cited_fact_ids"] = ["fact-unknown"]
        with self.assertRaises(ValueError):
            summarize_claim_review(
                run_fingerprint=FP,
                claims=claims,
                admitted_fact_ids=FACTS,
                review=make_review(["SUPPORTED", "SUPPORTED"]),
            )

    def test_no_citation_supported_rejected(self):
        claims = make_claims()
        claims[0]["cited_fact_ids"] = []
        with self.assertRaises(ValueError):
            summarize_claim_review(
                run_fingerprint=FP,
                claims=claims,
                admitted_fact_ids=FACTS,
                review=make_review(["SUPPORTED", "SUPPORTED"]),
            )

    def test_invalid_verdict_value(self):
        review = make_review(["SUPPORTED", "SUPPORTED"])
        review["items"][1]["verdict"] = "MAYBE"
        with self.assertRaises(ValueError):
            summarize_claim_review(
                run_fingerprint=FP,
                claims=make_claims(),
                admitted_fact_ids=FACTS,
                review=review,
            )

    def test_unknown_extra_field_in_claim(self):
        claims = make_claims()
        claims[0]["extra"] = "nope"
        with self.assertRaises(ValueError):
            summarize_claim_review(
                run_fingerprint=FP,
                claims=claims,
                admitted_fact_ids=FACTS,
                review=make_review(["SUPPORTED", "SUPPORTED"]),
            )

    def test_admitted_fact_ids_string_rejected(self):
        with self.assertRaises(ValueError):
            summarize_claim_review(
                run_fingerprint=FP,
                claims=make_claims(),
                admitted_fact_ids="fact-1fact-2",
                review=make_review(["SUPPORTED", "SUPPORTED"]),
            )

    def test_cited_fact_ids_string_rejected(self):
        claims = make_claims()
        claims[0]["cited_fact_ids"] = "fact-1"
        with self.assertRaises(ValueError):
            summarize_claim_review(
                run_fingerprint=FP,
                claims=claims,
                admitted_fact_ids=FACTS,
                review=make_review(["SUPPORTED", "SUPPORTED"]),
            )

    def test_no_raw_secret_detail_in_exception(self):
        secret = "sk-super-secret-token-12345"
        claims = make_claims()
        claims[0]["text"] = secret
        try:
            summarize_claim_review(
                run_fingerprint=FP,
                claims=claims,
                admitted_fact_ids=FACTS,
                review=make_review(["SUPPORTED", "SUPPORTED"]),
            )
            self.fail("expected ValueError")
        except ValueError as e:
            self.assertEqual(str(e), "INVALID_CLAIM_REVIEW")
            self.assertNotIn(secret, str(e))


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""Validation for the CANDIDATE funding-announcement evidence supplement.

Covers: provenance completeness, the excerpt vs structured-transcription
distinction, identity-chain discipline (Gumloop CONFIRMED by reference,
Delve PENDING, never invented), the '$'-alone currency discipline, window
arithmetic against the project's existing outcome window, hash binding to
the local transcription (not page bytes), collision detection, and that the
frozen Funding Y v1 files are untouched by any of this.
"""

import ast
import glob
import hashlib
import io
import json
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(SRC))
sys.path.insert(0, os.path.dirname(SRC))
sys.path.insert(0, SRC)

import build_funding_supplement as gen  # noqa: E402
import validate_funding_supplement as val  # noqa: E402

OUT_DIR = os.path.join(REPO, "data", "metadata", "funding_supplement")
FROZEN_LABELS = os.path.join(REPO, "results", "verified", "funding_y_v1", "company_labels.csv")
FROZEN_MANIFEST = os.path.join(REPO, "results", "verified", "funding_y_v1", "manifest.json")


def lf_sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read().replace(b"\r\n", b"\n")).hexdigest()


class TestGeneratorIsOfflineAndSelfContained(unittest.TestCase):

    def test_module_imports_nothing_that_can_reach_the_network(self):
        for fname in ("build_funding_supplement.py", "validate_funding_supplement.py"):
            tree = ast.parse(io.open(os.path.join(SRC, fname), encoding="utf-8").read())
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(a.name.split(".")[0] for a in node.names)
                elif isinstance(node, ast.ImportFrom) and node.module:
                    imported.add(node.module.split(".")[0])
            banned = {"requests", "urllib", "http", "socket", "ssl", "httpx",
                      "aiohttp", "subprocess", "sources"}
            self.assertEqual(imported & banned, set(), fname)

    def test_writes_only_inside_its_output_directory(self):
        """Functional, not textual: actually resolve --out against --repo
        and prove escaping paths are refused (ValueError, not a write)."""
        confined = gen.resolve_confined_out_dir(REPO, gen.OUT_DIR)
        self.assertEqual(confined, os.path.abspath(os.path.join(REPO, gen.OUT_DIR)))

        escapes = [
            os.path.join(REPO, "data", "metadata", "funding_supplement_evil"),
            os.path.join(REPO, "data", "metadata"),
            os.path.join(REPO, "..", "escaped_output"),
            os.path.abspath(os.path.join(REPO, "..", "..", "escaped_output")),
        ]
        for bad_out in escapes:
            with self.assertRaises(ValueError, msg=bad_out):
                gen.resolve_confined_out_dir(REPO, bad_out)

    def test_main_refuses_escaping_out_without_writing_any_file(self):
        tmp_repo = tempfile.mkdtemp()
        try:
            escape_dir = os.path.join(tmp_repo, "escaped")
            argv = ["build_funding_supplement.py", "--repo", tmp_repo, "--out", escape_dir]
            old_argv = sys.argv
            sys.argv = argv
            try:
                rc = gen.main()
            finally:
                sys.argv = old_argv
            self.assertEqual(rc, 1)
            self.assertFalse(os.path.exists(escape_dir))
        finally:
            shutil.rmtree(tmp_repo, ignore_errors=True)

    def test_frozen_funding_y_v1_unchanged_by_building_records(self):
        before_labels = lf_sha256(FROZEN_LABELS)
        before_manifest = lf_sha256(FROZEN_MANIFEST)
        gen.build_gumloop_record(REPO)
        gen.build_delve_record(REPO)
        self.assertEqual(lf_sha256(FROZEN_LABELS), before_labels)
        self.assertEqual(lf_sha256(FROZEN_MANIFEST), before_manifest)


class TestGeneratedRecords(unittest.TestCase):
    """Exercises the actual committed output, which this suite also
    regenerates once (determinism check) rather than trusting a stale file."""

    @classmethod
    def setUpClass(cls):
        cls.repo = REPO
        cls.records = [gen.build_gumloop_record(REPO), gen.build_delve_record(REPO)]
        cls.by_company = {r["company_id"]: r for r in cls.records}

    def test_exactly_two_seed_events_no_more(self):
        self.assertEqual(len(self.records), 2)
        self.assertEqual({r["company_id"] for r in self.records},
                         {"RM-agenthub", "RM-delve"})

    def test_determinism_rerun_is_byte_identical(self):
        first = [json.dumps(r, sort_keys=True) for r in self.records]
        second = [json.dumps(gen.build_gumloop_record(REPO), sort_keys=True),
                  json.dumps(gen.build_delve_record(REPO), sort_keys=True)]
        self.assertEqual(first, second)

    def test_provenance_fields_present_for_both(self):
        for rec in self.records:
            issues = val.check_provenance(rec)
            self.assertEqual(issues, [], rec["event_id"])
            self.assertEqual(rec["provenance"]["observed_capture_date"], "2026-11-05")

    def test_excerpt_and_transcription_are_kept_distinct(self):
        for rec in self.records:
            self.assertIn("provided_excerpt", rec)
            self.assertIsNone(rec["provided_excerpt"],
                              "coordinator supplied a structured transcription, "
                              "not an exact quote, for both Series A notes")
            self.assertIsInstance(rec["structured_transcription"], dict)
            self.assertEqual(val.check_excerpt_vs_transcription(rec), [])

    def test_gumloop_identity_confirmed_by_reference_not_recomputation(self):
        rec = self.by_company["RM-agenthub"]
        chain = rec["identity_chain"]
        self.assertEqual(chain["status"], "CONFIRMED")
        self.assertIn("agenthub_gumloop.json", chain["basis"])
        evidence = json.load(io.open(os.path.join(
            REPO, "data", "metadata", "rename_evidence", "agenthub_gumloop.json"),
            encoding="utf-8"))
        self.assertTrue(evidence["evidence_all_hold"])

    def test_gumloop_confirmed_identity_is_independent_of_open_yc_declaration(self):
        """The two must not be conflated: company declaration != YC declaration."""
        rec = self.by_company["RM-agenthub"]
        self.assertEqual(rec["identity_chain"]["status"], "CONFIRMED")
        evidence = json.load(io.open(os.path.join(
            REPO, "data", "metadata", "rename_evidence", "agenthub_gumloop.json"),
            encoding="utf-8"))
        self.assertFalse(evidence["official_yc_declaration_present"])
        self.assertTrue(evidence["company_first_party_declaration_present"])
        gaps = {g["id"]: g for g in evidence["gaps"]}
        self.assertEqual(gaps["G1"]["status"], "OPEN")

    def test_delve_identity_pending_not_confirmed(self):
        rec = self.by_company["RM-delve"]
        chain = rec["identity_chain"]
        self.assertEqual(chain["status"], "PENDING")
        self.assertTrue(chain["reason"])
        self.assertIn("domain", chain["what_would_close_this"].lower())

    def test_delve_identity_does_not_invent_a_domain_bind(self):
        rec = self.by_company["RM-delve"]
        transcription_text = json.dumps(rec["structured_transcription"])
        self.assertNotIn("getdelve.com", transcription_text)
        self.assertNotIn("delve.co", transcription_text)

    def test_currency_code_blank_for_both_dollar_sign_only_notes(self):
        for rec in self.records:
            self.assertIsNone(rec["amount"]["currency_code"])
            self.assertIsNone(rec["amount"]["numeric_value"])
            self.assertTrue(rec["amount"]["as_stated"])
            self.assertEqual(val.check_amount_discipline(rec), [])

    def test_gumloop_cumulative_total_not_conflated_with_event_amount(self):
        rec = self.by_company["RM-agenthub"]
        self.assertIn("CUMULATIVE",
                     rec["structured_transcription"]["cumulative_raised_mentioned"])
        self.assertEqual(rec["amount"]["as_stated"], "$17m")

    def test_delve_prior_round_not_created_as_a_separate_event(self):
        self.assertEqual(len(self.records), 2)
        rec = self.by_company["RM-delve"]
        self.assertIn("3.3M", rec["structured_transcription"]["prior_round_mentioned"])
        delve_records = [r for r in self.records if r["company_id"] == "RM-delve"]
        self.assertEqual(len(delve_records), 1)
        self.assertFalse(delve_records[0]["announced_date"].startswith("2024"))

    def test_window_check_matches_project_window(self):
        for rec in self.records:
            self.assertEqual(rec["window_check"]["window_start_exclusive"], "2024-04-04")
            self.assertEqual(rec["window_check"]["window_end_inclusive"], "2026-04-04")
            self.assertTrue(rec["window_check"]["in_window"])
            self.assertEqual(val.check_window(rec), [])

    def test_window_boundaries_are_exclusive_start_inclusive_end(self):
        self.assertFalse(gen.in_window("2024-04-04"))
        self.assertTrue(gen.in_window("2024-04-05"))
        self.assertTrue(gen.in_window("2026-04-04"))
        self.assertFalse(gen.in_window("2026-04-05"))

    def test_closing_status_never_claims_a_legal_close(self):
        for rec in self.records:
            self.assertTrue(rec["closing_status"].startswith("ANNOUNCEMENT_ONLY"))

    def test_hash_binds_local_transcription_not_page_bytes(self):
        for rec in self.records:
            self.assertEqual(val.check_hash(rec), [])
            expected = val.sha256_canonical(rec["structured_transcription"])
            self.assertEqual(rec["hash"]["value"], expected)
            self.assertIn("NOT", rec["hash"]["binds"])

    def test_hash_binds_false_page_archive_claim_is_rejected(self):
        """Review gap: a binds string that merely mentions 'original page
        bytes' without denying it (i.e. affirms the very claim this field
        promises to reject) must fail, not pass with zero issues."""
        rec = dict(self.records[0])
        rec["hash"] = dict(rec["hash"])
        rec["hash"]["binds"] = "SHA256 of original page bytes"
        rec["hash"]["value"] = val.sha256_canonical(rec["structured_transcription"])
        issues = val.check_hash(rec)
        self.assertTrue(any("does not explicitly DENY" in i for i in issues), issues)

    def test_hash_binds_missing_page_bytes_mention_is_rejected(self):
        rec = dict(self.records[0])
        rec["hash"] = dict(rec["hash"])
        rec["hash"]["binds"] = "the local structured_transcription object"
        rec["hash"]["value"] = val.sha256_canonical(rec["structured_transcription"])
        issues = val.check_hash(rec)
        self.assertTrue(any("must state it does NOT bind" in i for i in issues), issues)

    def test_admission_status_is_candidate_never_confirmed_label(self):
        for rec in self.records:
            self.assertEqual(rec["admission_status"], "CANDIDATE")
            self.assertEqual(val.check_admission_status(rec), [])

    def test_no_collisions_between_the_two_real_records(self):
        self.assertEqual(val.check_collisions(self.records), [])


class TestIdentityChainRegression(unittest.TestCase):
    """A CONFIRMED identity must be re-derived from a real, pinned, on-disk
    evidence file -- never trusted from an arbitrary basis string -- and its
    company_id must agree with the record it is attached to."""

    def test_confirmed_with_unchecked_basis_same_name_is_rejected(self):
        rec = {"company_id": "RM-delve",
               "identity_chain": {"status": "CONFIRMED", "company_id": "RM-delve",
                                  "basis": "same name"}}
        issues = val.check_identity_chain(rec)
        self.assertTrue(any("does not cite a checkable evidence file" in i
                            for i in issues), issues)

    def test_confirmed_citing_nonexistent_evidence_file_is_rejected(self):
        rec = {"company_id": "RM-delve",
               "identity_chain": {"status": "CONFIRMED", "company_id": "RM-delve",
                                  "basis": "data/metadata/rename_evidence/"
                                          "does_not_exist.json"}}
        issues = val.check_identity_chain(rec)
        self.assertTrue(any("does not exist on disk" in i for i in issues), issues)

    def test_confirmed_citing_real_evidence_for_a_different_company_is_rejected(self):
        rec = {"company_id": "RM-delve",
               "identity_chain": {"status": "CONFIRMED", "company_id": "RM-delve",
                                  "basis": "data/metadata/rename_evidence/"
                                          "agenthub_gumloop.json"}}
        issues = val.check_identity_chain(rec)
        self.assertTrue(any("company_id" in i for i in issues), issues)

    def test_confirmed_gumloop_basis_passes(self):
        rec = self.records_for_gumloop()
        self.assertEqual(val.check_identity_chain(rec), [])

    def test_identity_chain_company_id_mismatch_is_rejected(self):
        rec = self.records_for_gumloop()
        rec["identity_chain"]["company_id"] = "RM-some-other-company"
        issues = val.check_identity_chain(rec)
        self.assertTrue(any("does not match this record" in i for i in issues), issues)

    @staticmethod
    def records_for_gumloop():
        return gen.build_gumloop_record(REPO)


class TestCollisionRegression(unittest.TestCase):
    """Deliberately crafted duplicates must be caught, not silently merged."""

    def test_duplicate_event_id_detected(self):
        a = {"event_id": "FS-x-2025-01-01-series_a", "company_id": "RM-a",
             "announced_date": "2025-01-01", "event_type": "SERIES_A_ANNOUNCEMENT"}
        b = dict(a)
        issues = val.check_collisions([a, b])
        self.assertTrue(any("duplicate event_id" in i for i in issues))

    def test_duplicate_company_date_type_detected_even_with_different_ids(self):
        a = {"event_id": "FS-x-2025-01-01-series_a", "company_id": "RM-a",
             "announced_date": "2025-01-01", "event_type": "SERIES_A_ANNOUNCEMENT"}
        b = {"event_id": "FS-x-2025-01-01-series_a-dup", "company_id": "RM-a",
             "announced_date": "2025-01-01", "event_type": "SERIES_A_ANNOUNCEMENT"}
        issues = val.check_collisions([a, b])
        self.assertTrue(any("duplicate (company_id" in i for i in issues))

    def test_distinct_real_company_records_do_not_collide(self):
        records = [gen.build_gumloop_record(REPO), gen.build_delve_record(REPO)]
        self.assertEqual(val.check_collisions(records), [])


class TestAmountDisciplineRegression(unittest.TestCase):
    """A bare '$' must never fabricate a currency code or numeric amount."""

    def test_bare_dollar_sign_rejects_currency_code(self):
        rec = {
            "amount": {"as_stated": "$17m", "currency_code": "USD", "numeric_value": None},
            "structured_transcription": {"summary": "a $17m round"},
        }
        issues = val.check_amount_discipline(rec)
        self.assertTrue(any("bare" in i for i in issues))

    def test_explicit_currency_word_is_accepted(self):
        rec = {
            "amount": {"as_stated": "$17m", "currency_code": "USD", "numeric_value": None},
            "structured_transcription": {"summary": "a $17m (USD) round"},
        }
        self.assertEqual(val.check_amount_discipline(rec), [])

    def test_numeric_value_without_currency_is_rejected(self):
        rec = {
            "amount": {"as_stated": "$17m", "currency_code": None, "numeric_value": 17000000},
            "structured_transcription": {"summary": "a $17m round"},
        }
        issues = val.check_amount_discipline(rec)
        self.assertTrue(any("numeric_value" in i for i in issues))


class TestProvenanceRegression(unittest.TestCase):

    def test_missing_field_is_reported(self):
        rec = {"provenance": {"url": "https://x", "publisher": "x", "title": "x",
                              "publication_date": "2025-01-01",
                              "observed_capture_date": "2026-11-05",
                              "retrieved_by": "x"}}  # retrieval_note missing
        issues = val.check_provenance(rec)
        self.assertTrue(any("retrieval_note" in i for i in issues))

    def test_complete_provenance_passes(self):
        rec = {"provenance": {f: "x" for f in val.REQUIRED_PROVENANCE}}
        rec["provenance"]["url"] = "https://example.com/a"
        rec["provenance"]["publication_date"] = "2025-01-01"
        rec["provenance"]["observed_capture_date"] = "2026-11-05"
        rec["provenance"]["independent_corroboration"] = False
        self.assertEqual(val.check_provenance(rec), [])

    def test_malformed_url_is_rejected(self):
        rec = {"provenance": {f: "x" for f in val.REQUIRED_PROVENANCE}}
        rec["provenance"]["url"] = "not a URL"
        rec["provenance"]["publication_date"] = "2025-01-01"
        rec["provenance"]["observed_capture_date"] = "2026-11-05"
        rec["provenance"]["independent_corroboration"] = False
        issues = val.check_provenance(rec)
        self.assertTrue(any("not a well-formed https URL" in i for i in issues), issues)

    def test_unparseable_date_fields_are_rejected(self):
        rec = {"provenance": {f: "x" for f in val.REQUIRED_PROVENANCE}}
        rec["provenance"]["url"] = "https://example.com/a"
        rec["provenance"]["publication_date"] = "unknown"
        rec["provenance"]["observed_capture_date"] = "1900"
        rec["provenance"]["independent_corroboration"] = False
        issues = val.check_provenance(rec)
        self.assertTrue(any("publication_date" in i for i in issues), issues)
        self.assertTrue(any("observed_capture_date" in i for i in issues), issues)


class TestWindowRegression(unittest.TestCase):

    def test_mismatched_in_window_flag_is_caught(self):
        rec = {
            "announced_date": "2025-01-10",
            "window_check": {"window_start_exclusive": "2024-04-04",
                             "window_end_inclusive": "2026-04-04",
                             "in_window": False},  # wrong on purpose
            "closing_status": "ANNOUNCEMENT_ONLY -- x",
        }
        issues = val.check_window(rec)
        self.assertTrue(any("does not match recomputed" in i for i in issues))

    def test_missing_announcement_only_prefix_is_caught(self):
        rec = {
            "announced_date": "2025-01-10",
            "window_check": {"window_start_exclusive": "2024-04-04",
                             "window_end_inclusive": "2026-04-04",
                             "in_window": True},
            "closing_status": "CLOSED",
        }
        issues = val.check_window(rec)
        self.assertTrue(any("ANNOUNCEMENT_ONLY" in i for i in issues))

    def test_missing_announced_date_is_caught_even_when_in_window_is_false(self):
        rec = {
            "announced_date": None,
            "window_check": {"window_start_exclusive": "2024-04-04",
                             "window_end_inclusive": "2026-04-04",
                             "in_window": False},
            "closing_status": "ANNOUNCEMENT_ONLY -- x",
        }
        issues = val.check_window(rec)
        self.assertTrue(any("missing announced_date" in i for i in issues), issues)

    def test_impossible_calendar_date_is_not_silently_treated_as_in_window(self):
        rec = {
            "announced_date": "2025-02-31",
            "window_check": {"window_start_exclusive": "2024-04-04",
                             "window_end_inclusive": "2026-04-04",
                             "in_window": True},  # wrongly claimed in-window
            "closing_status": "ANNOUNCEMENT_ONLY -- x",
        }
        issues = val.check_window(rec)
        self.assertTrue(any("not a valid calendar date" in i for i in issues), issues)
        self.assertFalse(val.in_window("2025-02-31"))


class TestManifestCountsStaySeparateFromFundingYV1(unittest.TestCase):

    def setUp(self):
        self.records = [gen.build_gumloop_record(REPO), gen.build_delve_record(REPO)]
        self.manifest = gen.build_manifest(REPO, self.records)

    def test_counts_are_reported_as_distinct_fields(self):
        counts = self.manifest["counts"]
        self.assertEqual(counts["candidate_announcement_events"], 2)
        self.assertEqual(counts["identity_confirmed"], 1)
        self.assertEqual(counts["identity_pending"], 1)
        self.assertEqual(counts["events_in_outcome_window"], 2)

    def test_manifest_never_claims_an_overall_y_update(self):
        issues = val.check_manifest_counts(self.records, self.manifest)
        self.assertEqual(issues, [])
        blob = json.dumps(self.manifest)
        for forbidden in ("funding_y_total", "updated_funding_y_count",
                         "confirmed_positive_companies", "overall_y_count"):
            self.assertNotIn(forbidden, blob)

    def test_network_requests_made_is_zero(self):
        self.assertEqual(self.manifest["network_requests_made"], 0)

    def test_manifest_explicitly_disclaims_funding_y_v1_update(self):
        text = " ".join(self.manifest["explicitly_not_this"])
        self.assertIn("Funding Y v1", text)
        self.assertIn("freeze_funding_y_v1.py", text)

    def test_real_manifest_input_hashes_match_files_on_disk(self):
        self.assertEqual(val.check_manifest_input_hashes(self.manifest, self.records), [])

    def test_tampered_input_hash_is_caught_against_pinned_evidence(self):
        tampered = dict(self.manifest)
        tampered["input_hashes"] = dict(self.manifest["input_hashes"])
        a_key = next(iter(tampered["input_hashes"]))
        tampered["input_hashes"][a_key] = "0" * 64
        issues = val.check_manifest_input_hashes(tampered, self.records)
        self.assertTrue(any("does not match the recomputed hash" in i for i in issues), issues)

    def test_input_hash_referencing_missing_file_is_caught(self):
        tampered = dict(self.manifest)
        tampered["input_hashes"] = dict(self.manifest["input_hashes"])
        tampered["input_hashes"]["data/metadata/does_not_exist.json"] = "0" * 64
        issues = val.check_manifest_input_hashes(tampered, self.records)
        self.assertTrue(any("does not exist on disk" in i for i in issues), issues)

    def test_empty_input_hashes_is_caught(self):
        issues = val.check_manifest_input_hashes({"input_hashes": {}}, self.records)
        self.assertTrue(any("missing/empty" in i for i in issues), issues)

    def test_dropping_rename_evidence_and_panel_hash_is_caught(self):
        """Review gap: keeping only the cohort hash and dropping both the
        rename-evidence and panel hashes must fail, not pass -- those
        inputs are what the CONFIRMED identity chain actually depends on."""
        tampered = dict(self.manifest)
        cohort_only = {k: v for k, v in self.manifest["input_hashes"].items()
                      if k == "data/processed/w24_spreadsheet_2024-03-25.csv"}
        tampered["input_hashes"] = cohort_only
        issues = val.check_manifest_input_hashes(tampered, self.records)
        self.assertTrue(any("missing required pinned input" in i for i in issues), issues)
        joined = " ".join(issues)
        self.assertIn("rename_evidence/agenthub_gumloop.json", joined)
        self.assertIn("yc2024_monthly.csv", joined)

    def test_dropping_only_panel_hash_is_caught(self):
        tampered = dict(self.manifest)
        tampered["input_hashes"] = {
            k: v for k, v in self.manifest["input_hashes"].items()
            if k != "data/processed/yc2024_monthly.csv"}
        issues = val.check_manifest_input_hashes(tampered, self.records)
        self.assertTrue(any("yc2024_monthly.csv" in i for i in issues), issues)

    def test_required_input_hash_paths_includes_confirmed_basis_only(self):
        pending_only = [gen.build_delve_record(REPO)]
        required = val.required_input_hash_paths(pending_only)
        self.assertNotIn("data/metadata/rename_evidence/agenthub_gumloop.json", required)
        self.assertIn("data/processed/w24_spreadsheet_2024-03-25.csv", required)
        self.assertIn("data/processed/yc2024_monthly.csv", required)


class TestCommittedOutputOnDisk(unittest.TestCase):
    """If the generator has been run and committed, the files on disk must
    pass the validator with zero issues. Skips if not yet generated."""

    def test_committed_files_validate_clean(self):
        if not os.path.isdir(OUT_DIR):
            self.skipTest("data/metadata/funding_supplement not yet generated")
        if not glob.glob(os.path.join(OUT_DIR, "*.json")):
            self.skipTest("data/metadata/funding_supplement is empty")
        report = val.validate_all(OUT_DIR)
        self.assertEqual(report, {})

    def test_committed_files_never_wrote_outside_their_directory(self):
        if not os.path.isdir(OUT_DIR):
            self.skipTest("data/metadata/funding_supplement not yet generated")
        self.assertTrue(lf_sha256(FROZEN_LABELS))  # frozen v1 still readable
        self.assertTrue(lf_sha256(FROZEN_MANIFEST))


if __name__ == "__main__":
    unittest.main()

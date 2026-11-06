# -*- coding: utf-8 -*-
"""Validation for the offline re-match and the AgentHub->Gumloop evidence record.

The point of these tests is to stop the two results being conflated. An entity
match is an identity claim; an in-window funding event is an outcome claim.
A >= B is asserted, and the one company that resolved is asserted to have added
NO funding evidence, because its round detail is not in the local cache.

Cache-dependent tests skip rather than fail when the gitignored cache is absent,
so a fresh clone does not look broken.
"""
import ast
import csv
import hashlib
import io
import json
import os
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
REPO = os.path.dirname(os.path.dirname(SRC))
sys.path.insert(0, os.path.dirname(SRC))
sys.path.insert(0, SRC)

from entity_resolution.normalize import norm_domain  # noqa: E402
from rematch_offline import (in_window, classify, query_tag, lf_sha256,  # noqa: E402
                             WINDOW_START, WINDOW_END)

OUT = os.path.join(REPO, "data", "interim", "rematch_offline")
RES = os.path.join(OUT, "rematch_entity_resolution.csv")
EVENTS = os.path.join(OUT, "rematch_candidate_events.csv")
GAPS = os.path.join(OUT, "rematch_gaps.csv")
MANIFEST = os.path.join(OUT, "rematch_manifest.json")
CACHE = os.path.join(REPO, "data", "interim", "funding_source_benchmark",
                     "raw_recentfunding")
EVIDENCE = os.path.join(REPO, "data", "metadata", "rename_evidence",
                        "agenthub_gumloop.json")
REPAIRED = os.path.join(REPO, "data", "interim", "identifier_repair",
                        "company_identifiers_repaired.csv")

HAVE_CACHE = os.path.isdir(CACHE)


def rows(path):
    return list(csv.DictReader(io.open(path, encoding="utf-8-sig")))


class TestWindowSemanticsMatchTheBenchmark(unittest.TestCase):
    """The window must be the project's, not a new one invented here."""

    def test_boundaries(self):
        self.assertEqual((WINDOW_START, WINDOW_END), ("2024-04-04", "2026-04-04"))
        self.assertFalse(in_window("2024-04-04"), "start is EXCLUSIVE")
        self.assertTrue(in_window("2024-04-05"))
        self.assertTrue(in_window("2026-04-04"), "end is INCLUSIVE")
        self.assertFalse(in_window("2026-04-05"))

    def test_classification(self):
        self.assertEqual(classify(""), "NO_DATE")
        self.assertEqual(classify("2024-01-01"), "PRE_DECISION")
        self.assertEqual(classify("2024-04-04"), "PRE_DECISION")
        self.assertEqual(classify("2025-01-10"), "IN_WINDOW")
        self.assertEqual(classify("2026-12-01"), "POST_CUTOFF")

    def test_cache_key_matches_the_original_fetcher(self):
        # run_recentfunding_benchmark used "q_" + norm_name(q).replace(" ", "_")
        self.assertEqual(query_tag("Just Words"), "q_just_words")
        self.assertEqual(query_tag("Gumloop"), "q_gumloop")
        self.assertEqual(query_tag("Blitz AI"), "q_blitz_ai")
        self.assertEqual(query_tag("Delve LLC"), "q_delve")  # legal suffix stripped


class TestTheTwoNumbersStaySeparate(unittest.TestCase):

    def setUp(self):
        self.m = json.load(io.open(MANIFEST, encoding="utf-8"))
        self.res = rows(RES)

    def test_manifest_reports_them_as_two_fields(self):
        self.assertIn("A_entity_matches_recovered", self.m)
        self.assertIn("B_companies_with_new_in_window_funding_evidence", self.m)
        self.assertIn("numbers_are_separate", self.m)

    def test_A_is_at_least_B(self):
        self.assertGreaterEqual(self.m["A_entity_matches_recovered"],
                                self.m["B_companies_with_new_in_window_funding_evidence"])

    def test_numbers_agree_with_the_per_company_rows(self):
        self.assertEqual(self.m["A_entity_matches_recovered"],
                         sum(1 for r in self.res if r["entity_recovered"] == "YES"))
        self.assertEqual(self.m["B_companies_with_new_in_window_funding_evidence"],
                         sum(1 for r in self.res if r["funding_evidence_added"] == "YES"))

    def test_funding_evidence_requires_an_actual_in_window_event_row(self):
        ev = rows(EVENTS)
        claimed = {r["company_id"] for r in self.res if r["funding_evidence_added"] == "YES"}
        backed = {e["company_id"] for e in ev if e["window_class"] == "IN_WINDOW"}
        self.assertEqual(claimed, backed,
                         "a company may only count in B if an in-window event row exists")

    def test_an_entity_match_alone_never_counts_as_funding_evidence(self):
        for r in self.res:
            if r["new_match_status"] == "ENTITY_MATCHED_NO_DETAIL_CACHED":
                self.assertEqual(r["entity_recovered"], "YES")
                self.assertEqual(r["funding_evidence_added"], "NO")
                self.assertEqual(int(r["events_in_window"]), 0)


class TestResolutionResults(unittest.TestCase):

    def setUp(self):
        self.res = {r["company_id"]: r for r in rows(RES)}
        self.rep = {r["company_id"]: r for r in rows(REPAIRED)}

    def test_agenthub_resolves_to_gumloop_but_adds_no_funding_evidence(self):
        r = self.res["RM-agenthub"]
        self.assertEqual(r["old_match_status"], "COMPANY_NOT_FOUND")
        self.assertEqual(r["matched_slug"], "gumloop")
        self.assertEqual(r["resolution_method"], "ROSTER_W24_NAME")
        self.assertEqual(r["new_match_status"], "ENTITY_MATCHED_NO_DETAIL_CACHED")
        self.assertEqual(r["detail_cache_present"], "NO")
        self.assertEqual(r["entity_recovered"], "YES")
        self.assertEqual(r["funding_evidence_added"], "NO")

    def test_roster_method_does_not_claim_a_domain_check_it_could_not_do(self):
        r = self.res["RM-agenthub"]
        self.assertIn("roster carries no website", r["evidence"])
        self.assertEqual(r["matched_website"], "")

    def test_arcane_resolves_on_a_domain_that_is_genuinely_ours(self):
        r = self.res["arcane"]
        self.assertEqual(r["resolution_method"], "CACHED_SEARCH_DOMAIN")
        self.assertEqual(r["matched_slug"], "arcane")
        self.assertEqual(r["matched_website"], "rohanmehta.com")
        ours = {norm_domain(d) for d in self.rep["arcane"]["query_domains"].split("|")}
        self.assertIn("rohanmehta.com", ours,
                      "the match is only legitimate because the panel published "
                      "this domain for this company")
        self.assertEqual(r["funding_evidence_added"], "NO")

    def test_no_slug_is_stolen_from_another_company(self):
        orig = {x["matched_slug"]: x["company_id"] for x in rows(os.path.join(
            REPO, "data/interim/funding_source_benchmark/"
                  "recentfunding_company_matches.csv")) if x.get("matched_slug")}
        for r in self.res.values():
            if r["matched_slug"] and r["matched_slug"] in orig:
                self.assertEqual(orig[r["matched_slug"]], r["company_id"],
                                 "slug %s reassigned away from %s"
                                 % (r["matched_slug"], orig[r["matched_slug"]]))

    def test_no_two_companies_resolve_to_the_same_slug(self):
        seen = {}
        for r in self.res.values():
            if r["matched_slug"]:
                self.assertNotIn(r["matched_slug"], seen)
                seen[r["matched_slug"]] = r["company_id"]

    def test_unresolved_companies_state_why(self):
        for r in self.res.values():
            if not r["matched_slug"]:
                self.assertTrue(r["note"], "%s has no slug and no reason" % r["company_id"])


class TestGapsAreRecorded(unittest.TestCase):

    def setUp(self):
        self.gaps = rows(GAPS)

    def test_gumloop_detail_gap_is_recorded_explicitly(self):
        g = [x for x in self.gaps
             if x["company_id"] == "RM-agenthub" and x["gap_kind"] == "DETAIL_NOT_CACHED"]
        self.assertEqual(len(g), 1)
        self.assertIn("rf_c_gumloop.json", g[0]["detail"])
        self.assertIn("/companies/gumloop", g[0]["how_to_close"])

    @unittest.skipUnless(HAVE_CACHE, "local cache absent")
    def test_the_gap_is_real_the_file_really_is_missing(self):
        self.assertFalse(os.path.exists(os.path.join(CACHE, "rf_c_gumloop.json")))
        self.assertFalse(os.path.exists(os.path.join(CACHE, "rf_q_gumloop.json")))

    def test_uncached_search_for_a_repaired_name_is_recorded(self):
        g = [x for x in self.gaps
             if x["company_id"] == "RM-agenthub" and x["gap_kind"] == "SEARCH_NOT_CACHED"]
        self.assertEqual(len(g), 1)
        self.assertIn("rf_q_gumloop.json", g[0]["detail"])

    def test_every_gap_says_how_to_close_it(self):
        self.assertTrue(self.gaps)
        for g in self.gaps:
            self.assertTrue(g["how_to_close"])
            self.assertIn(g["gap_kind"], ("DETAIL_NOT_CACHED", "SEARCH_NOT_CACHED",
                                          "ACQUIRED_IDENTITY_CAVEAT"))


class TestIdentityCaveat(unittest.TestCase):
    """A matched domain is only as trustworthy as what it identifies. An
    acquired company's leftover domain (here, a founder's personal site) must
    not be read as continuing corporate identity without a recorded caveat.
    """

    def setUp(self):
        self.res = {r["company_id"]: r for r in rows(RES)}
        self.outcomes = {r["entity_id"]: r for r in rows(os.path.join(
            REPO, "data", "processed", "w24_raw_outcomes_24m.csv"))}

    def test_arcane_caveat_fires_because_the_panel_says_acquired(self):
        r = self.res["arcane"]
        self.assertEqual(self.outcomes["arcane"]["acquired_by_cutoff"], "YES")
        self.assertEqual(r["acquired_by_cutoff"], "YES")
        self.assertTrue(r["identity_caveat"], "arcane must carry a caveat")
        self.assertIn("acquired_by_cutoff=YES", r["identity_caveat"])
        self.assertIn("rohanmehta.com", r["identity_caveat"])

    def test_agenthub_has_no_caveat_because_acquisition_status_is_unknown(self):
        r = self.res["RM-agenthub"]
        self.assertEqual(self.outcomes["RM-agenthub"]["acquired_by_cutoff"], "UNKNOWN")
        self.assertEqual(r["identity_caveat"], "",
                         "no caveat may be invented where acquisition status is unknown")

    def test_every_row_with_a_caveat_is_backed_by_acquired_yes_in_the_panel(self):
        """The caveat is a cross-check of the panel, not a guess: it may only
        ever appear where the panel itself records acquired_by_cutoff=YES."""
        for r in self.res.values():
            if r["identity_caveat"]:
                self.assertEqual(r["acquired_by_cutoff"], "YES", r["company_id"])
                self.assertEqual(self.outcomes[r["company_id"]]["acquired_by_cutoff"],
                                 "YES", r["company_id"])

    def test_caveat_only_fires_when_the_matched_domain_differs_from_decision_domain(self):
        """Resolving to the company's OWN decision-date domain is not a
        founder/acquirer placeholder and must never be caveated."""
        rep = {r["company_id"]: r for r in rows(REPAIRED)}
        for r in self.res.values():
            if r["acquired_by_cutoff"] == "YES" and r["matched_website"]:
                decision_dom = norm_domain(rep[r["company_id"]]["domain_at_decision"])
                if r["matched_website"] == decision_dom:
                    self.assertEqual(r["identity_caveat"], "", r["company_id"])

    def test_manifest_counts_caveats_consistently_with_the_rows(self):
        m = json.load(io.open(MANIFEST, encoding="utf-8"))
        self.assertEqual(m["entity_matches_with_identity_caveat"],
                         sum(1 for r in self.res.values() if r["identity_caveat"]))


class TestNothingWasInventedOrSpent(unittest.TestCase):

    def test_manifest_records_zero_calls_and_zero_inferred_amounts(self):
        m = json.load(io.open(MANIFEST, encoding="utf-8"))
        self.assertEqual(m["new_api_calls"], 0)
        self.assertEqual(m["amounts_inferred"], 0)
        self.assertFalse(m["cache"]["committed"])

    def test_total_raised_was_never_converted_into_an_event(self):
        """The roster gives Gumloop a cumulative total_raised. A cumulative
        total is not a dated round and must not become one."""
        for e in rows(EVENTS):
            self.assertNotEqual(e["company_id"], "RM-agenthub")
            self.assertTrue(e["event_date"], "an event row with no date is not evidence")

    def test_no_event_row_lacks_a_window_class(self):
        for e in rows(EVENTS):
            self.assertIn(e["window_class"],
                          ("IN_WINDOW", "PRE_DECISION", "POST_CUTOFF", "NO_DATE"))

    def test_module_imports_nothing_that_can_reach_the_network(self):
        tree = ast.parse(io.open(os.path.join(SRC, "rematch_offline.py"),
                                 encoding="utf-8").read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        banned = {"requests", "urllib", "http", "socket", "ssl", "httpx",
                  "aiohttp", "subprocess", "sources"}
        self.assertEqual(imported & banned, set())

    def test_writes_only_inside_its_output_directory(self):
        src = io.open(os.path.join(SRC, "rematch_offline.py"), encoding="utf-8").read()
        tree = ast.parse(src)
        writes = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if not ((isinstance(fn, ast.Name) and fn.id == "open")
                    or (isinstance(fn, ast.Attribute) and fn.attr == "open")):
                continue
            mode = node.args[1].value if (len(node.args) > 1 and
                                          isinstance(node.args[1], ast.Constant)) else ""
            if "w" not in str(mode) and "a" not in str(mode):
                continue
            writes += 1
            target = ast.unparse(node.args[0])
            self.assertTrue("out_dir" in target or "mpath" in target or target == "path",
                            "write target %r escapes the output directory" % target)
        self.assertGreaterEqual(writes, 2)

    def test_frozen_funding_y_v1_unchanged(self):
        m = json.load(io.open(MANIFEST, encoding="utf-8"))
        for rel, digest in m["frozen_funding_y_v1_untouched"].items():
            self.assertEqual(lf_sha256(os.path.join(REPO, rel)), digest, rel)


class TestRenameEvidenceRecord(unittest.TestCase):

    def setUp(self):
        self.e = json.load(io.open(EVIDENCE, encoding="utf-8"))

    def test_all_five_evidence_items_hold(self):
        ids = [x["id"] for x in self.e["evidence"]]
        self.assertEqual(ids, ["E1", "E2", "E3", "E4", "E5"])
        for x in self.e["evidence"]:
            self.assertTrue(x["holds"], x["id"])
        self.assertTrue(self.e["evidence_all_hold"])

    def test_e1_and_e2_are_not_counted_as_independent_of_each_other(self):
        """E1 and E2 are both derived from the SAME two internal files (our
        own panel and our own cohort sheet) - they are the structural bridge
        itself, not independent corroboration of it. Only E3 (RecentFunding),
        E4 (Preqin) and E5 (company blog) are independent of our own files."""
        e1, e2 = self.e["evidence"][0], self.e["evidence"][1]
        self.assertEqual(set(e1["sources"]), set(e2["sources"]))
        for kind in ("EXACT_STRING_1TO1_BRIDGE", "PANEL_CONTINUITY"):
            self.assertIn(kind, [x["kind"] for x in self.e["evidence"][:2]])

    def test_short_description_uniqueness_alone_is_not_treated_as_a_merge_authority(self):
        """E1 explicitly disclaims deciding the merge by itself; the merge
        this file documents stands on five items, not E1 alone."""
        e1 = self.e["evidence"][0]
        self.assertIn("does_not_establish", e1)
        self.assertNotIn("confirmed", e1["establishes"].lower())
        self.assertGreater(len(self.e["evidence"]), 1)

    def test_e5_is_a_company_statement_not_a_yc_declaration(self):
        e5 = self.e["evidence"][4]
        self.assertEqual(e5["kind"], "COMPANY_FIRST_PARTY_DECLARATION")
        self.assertFalse(e5["declaration"]["is_yc_issued"])
        self.assertIn("AgentHub.dev", e5["declaration"]["excerpt"])
        self.assertIn("coordinator", e5["declaration"]["retrieved_by"])
        self.assertIn("coordinator", e5["sources"][0])
        self.assertTrue(self.e["company_first_party_declaration_present"])
        self.assertFalse(self.e["official_yc_declaration_present"],
                         "a company statement must never be recorded as a YC declaration")

    def test_total_raised_discrepancy_is_flagged_not_resolved(self):
        gaps = {g["id"]: g for g in self.e["gaps"]}
        self.assertIn("G3", gaps)
        self.assertEqual(gaps["G3"]["status"], "OPEN")
        self.assertIn("70,600,000", gaps["G3"]["detail"])
        self.assertIn("20m", gaps["G3"]["detail"])

    def test_the_bridge_is_one_to_one_on_both_sides(self):
        e1 = self.e["evidence"][0]
        self.assertEqual(e1["cohort_companies_with_this_string"], ["AgentHub"])
        self.assertEqual(e1["panel_slugs_with_this_string"], ["gumloop"])

    def test_third_party_places_gumloop_in_w24_and_knows_no_agenthub(self):
        e3 = self.e["evidence"][2]
        self.assertEqual(len(e3["gumloop_entries"]), 1)
        self.assertEqual(e3["gumloop_entries"][0]["cohort"], "YC W24")
        self.assertEqual(e3["agenthub_entries"], [])
        # and it must say what that does NOT prove
        self.assertIn("194", e3["does_not_establish"])

    def test_geography_corroboration_is_stated_with_its_limit(self):
        e4 = self.e["evidence"][3]
        self.assertEqual(e4["preqin"]["portfolio_company_state"], "BC")
        self.assertEqual(e4["preqin"]["portfolio_company_country"], "Canada")
        self.assertIn("BC", e4["agenthub_location_at_decision"])
        self.assertEqual(len(e4["preqin"]["deals"]), 2)
        for d in e4["preqin"]["deals"]:
            self.assertNotIn("amount", d, "no unconfirmed amount may be recorded")
        self.assertIn("Char(1)", e4["does_not_establish"])

    def test_no_official_yc_declaration_is_claimed(self):
        self.assertFalse(self.e["official_yc_declaration_present"])
        self.assertEqual(self.e["network_requests_made"], 0)
        gaps = {g["id"]: g for g in self.e["gaps"]}
        self.assertEqual(gaps["G1"]["status"], "OPEN")
        self.assertEqual(gaps["G2"]["status"], "OPEN")
        self.assertIn("former_names", gaps["G1"]["detail"])

    def test_identity_fields_agree_with_the_repaired_set(self):
        rep = {r["company_id"]: r for r in rows(REPAIRED)}["RM-agenthub"]
        self.assertEqual(self.e["name_at_decision"], rep["name_at_decision"])
        self.assertEqual(self.e["domain_at_decision"], rep["domain_at_decision"])
        self.assertEqual(self.e["current_domain"], rep["current_domain"])
        self.assertEqual(self.e["current_slug"], rep["current_slug"])


class TestDeterminism(unittest.TestCase):

    @unittest.skipUnless(HAVE_CACHE, "local cache absent")
    def test_both_scripts_rerun_byte_identical(self):
        paths = [RES, EVENTS, GAPS, MANIFEST, EVIDENCE]
        before = {p: hashlib.sha256(open(p, "rb").read()).hexdigest() for p in paths}
        for script in ("rematch_offline.py", "build_rename_evidence.py"):
            r = subprocess.run([sys.executable, os.path.join(SRC, script),
                                "--repo", REPO], capture_output=True, text=True)
            self.assertEqual(r.returncode, 0, r.stderr[-800:])
        for p, h in before.items():
            self.assertEqual(hashlib.sha256(open(p, "rb").read()).hexdigest(), h,
                             "%s is not reproducible" % os.path.basename(p))


if __name__ == "__main__":
    unittest.main(verbosity=2)

# -*- coding: utf-8 -*-
"""Validation for the offline identifier repair.

Positive controls, as instructed:
    AgentHub -> Gumloop   (name, slug and domain all changed at once)
    Delve                 (domain changed getdelve.com -> delve.co)

Rejection controls, as instructed:
    Delve Bio and the other same-name Preqin companies must be REFUSED.

Plus the invariants that make the repair safe to trust: nothing fuzzy, nothing
lost, no chain shared by two companies, no amount written anywhere, the frozen
Funding Y v1 untouched, and byte-identical output on a rerun.
"""
import csv
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)                      # src/funding
REPO = os.path.dirname(os.path.dirname(SRC))     # repo root
sys.path.insert(0, os.path.dirname(SRC))         # src
sys.path.insert(0, SRC)

from entity_resolution.normalize import norm_domain, norm_name  # noqa: E402
from repair_company_identifiers import (domain_contradicts, norm_oneliner,  # noqa: E402
                                        is_truncated, Panel, lf_sha256)

OUT = os.path.join(REPO, "data", "interim", "identifier_repair")
REPAIRED = os.path.join(OUT, "company_identifiers_repaired.csv")
BEFORE_AFTER = os.path.join(OUT, "identifier_repair_before_after.csv")
UNRESOLVED = os.path.join(OUT, "identifier_repair_unresolved.csv")
EVIDENCE = os.path.join(OUT, "identifier_repair_evidence.csv")
MANIFEST = os.path.join(OUT, "identifier_repair_manifest.json")

# The six same-name companies Preqin returned for the query "Delve", none of
# which is ours. Recorded in docs/research_log/2026-11-05_wrds_funding_source_probe.md
PREQIN_DELVE_DECOYS = {
    "Delve Bio Inc.": "www.delve.bio",
    "Delve Labs Inc.": "www.delvesecurity.com",
    "Delve LLC": "www.delve.com",
    "Delve Networks": "www.delvenetworks.com",
}


def rows(path):
    return list(csv.DictReader(io.open(path, encoding="utf-8-sig")))


def by_id(path):
    return {r["company_id"]: r for r in rows(path)}


class TestPositiveControls(unittest.TestCase):

    def setUp(self):
        self.rep = by_id(REPAIRED)

    def test_agenthub_resolves_to_gumloop_with_traceable_evidence(self):
        r = self.rep["RM-agenthub"]
        self.assertEqual(r["current_name"], "Gumloop")
        self.assertEqual(r["current_domain"], "gumloop.com")
        self.assertEqual(r["current_slug"], "gumloop")
        self.assertEqual(r["resolution_tier"], "T3_ONELINER")
        # the link must be justified by a recorded, checkable key
        self.assertTrue(r["evidence_key"].startswith("oneliner:"))
        self.assertEqual(r["evidence_snapshot"], "2024-10-01")
        self.assertEqual(r["evidence_source"], "data/processed/yc2024_monthly.csv")
        self.assertEqual(r["renamed_observed"], "YES")

    def test_agenthub_keeps_its_old_name_and_old_domain(self):
        r = self.rep["RM-agenthub"]
        self.assertEqual(r["name_at_decision"], "AgentHub")
        self.assertEqual(r["domain_at_decision"], "agenthub.dev")
        self.assertIn("AgentHub", r["query_names"].split("|"))
        self.assertIn("Gumloop", r["query_names"].split("|"))
        self.assertIn("agenthub.dev", r["query_domains"].split("|"))
        self.assertIn("gumloop.com", r["query_domains"].split("|"))
        # newest identity must be tried first
        self.assertEqual(r["query_domains"].split("|")[0], "gumloop.com")

    def test_agenthub_oneliner_evidence_exists_verbatim_in_both_files(self):
        """The asserted bridge must be checkable by hand, not taken on trust."""
        sheet = rows(os.path.join(REPO, "data/processed/w24_spreadsheet_2024-03-25.csv"))
        panel = rows(os.path.join(REPO, "data/processed/yc2024_monthly.csv"))
        key = self.rep["RM-agenthub"]["evidence_key"].split(":", 1)[1]
        sheet_hits = [s for s in sheet
                      if norm_oneliner(s.get("Short Description")) == key]
        panel_hits = [p for p in panel
                      if p.get("batch") == "winter-2024"
                      and norm_oneliner(p.get("one_liner")) == key]
        self.assertEqual([s["Company Name"] for s in sheet_hits], ["AgentHub"])
        self.assertTrue(panel_hits)
        self.assertEqual({p["slug"] for p in panel_hits}, {"gumloop"})

    def test_delve_gains_the_new_domain_and_keeps_the_old_one(self):
        r = self.rep["RM-delve"]
        observed = r["observed_domains"].split("|")
        self.assertIn("getdelve.com", observed)
        self.assertIn("delve.co", observed)
        self.assertEqual(observed.index("getdelve.com"), 0,
                         "observed domains must be oldest-first")
        q = r["query_domains"].split("|")
        self.assertEqual(q[0], "delve.co", "newest domain is queried first")
        self.assertIn("getdelve.com", q)
        self.assertEqual(r["resolution_tier"], "T1_SLUG")
        self.assertEqual(r["evidence_key"], "slug:delve")

    def test_delve_new_domain_is_actually_in_the_panel(self):
        panel = rows(os.path.join(REPO, "data/processed/yc2024_monthly.csv"))
        doms = {norm_domain(p.get("website")) for p in panel
                if p.get("batch") == "winter-2024" and p.get("slug") == "delve"}
        self.assertIn("delve.co", doms)
        self.assertIn("getdelve.com", doms)


class TestRejectionControls(unittest.TestCase):

    def setUp(self):
        self.delve = by_id(REPAIRED)["RM-delve"]["query_domains"].split("|")

    def test_every_preqin_delve_decoy_is_refused_on_domain(self):
        for name, site in sorted(PREQIN_DELVE_DECOYS.items()):
            self.assertTrue(domain_contradicts(self.delve, site),
                            "%s (%s) must be refused against %s"
                            % (name, site, self.delve))

    def test_our_own_domains_are_not_refused(self):
        for d in self.delve:
            self.assertFalse(domain_contradicts(self.delve, d))

    def test_lantern_collision_still_refused(self):
        """The original false-match regression, kept as a live test."""
        self.assertTrue(domain_contradicts(["lantern.dev"], "lanternhq.com"))
        self.assertFalse(domain_contradicts(["lantern.dev"], "lantern.dev"))

    def test_no_domain_is_not_treated_as_contradiction(self):
        self.assertFalse(domain_contradicts([], "delve.bio"))
        self.assertFalse(domain_contradicts(["delve.co"], ""))

    def test_delve_bio_is_not_the_same_name_as_delve(self):
        """No fuzzy name matching: a longer descriptive name is a DIFFERENT name."""
        self.assertNotEqual(norm_name("Delve Bio Inc."), norm_name("Delve"))
        self.assertEqual(norm_name("Delve Bio Inc."), "delve bio")
        self.assertEqual(norm_name("Delve LLC"), "delve")  # legal suffix only

    def test_agenthub_does_not_match_its_lookup_near_misses(self):
        for other in ["Agentuity Inc.", "AgentLabs Inc.", "AgentHome LLC", "Agentbox"]:
            self.assertNotEqual(norm_name(other), norm_name("AgentHub"))

    def test_oneliner_key_is_exact_not_fuzzy(self):
        a = "AI that makes compliance effortless"
        self.assertEqual(norm_oneliner(a), norm_oneliner("  ai that makes  compliance effortless. "))
        self.assertNotEqual(norm_oneliner(a), norm_oneliner("AI that makes compliance easy"))
        self.assertNotEqual(norm_oneliner(a), norm_oneliner("AI that makes compliance"))

    def test_truncated_oneliners_are_never_used_as_evidence(self):
        self.assertTrue(is_truncated("A no-code platform for creating agents and…"))
        self.assertTrue(is_truncated("something long..."))
        self.assertFalse(is_truncated("A no-code platform for automating workflows with AI"))


class TestInvariants(unittest.TestCase):

    def setUp(self):
        self.rep = rows(REPAIRED)
        self.ba = rows(BEFORE_AFTER)

    def test_cohort_size_is_unchanged(self):
        self.assertEqual(len(self.rep), 240)
        self.assertEqual(len(self.ba), 240)
        self.assertEqual(len({r["company_id"] for r in self.rep}), 240)

    def test_no_company_loses_a_domain_it_already_had(self):
        lost = [r["company_id"] for r in self.ba
                if r["current_domain_before"] and not r["current_domain_after"]]
        self.assertEqual(lost, [], "repair must never remove resolution we had")

    def test_no_company_loses_a_query_name_or_domain_it_already_had(self):
        for r in self.ba:
            before_n = {x for x in r["query_names_before"].split("|") if x}
            after_n = {x for x in r["query_names_after"].split("|") if x}
            before_d = {x for x in r["query_domains_before"].split("|") if x}
            after_d = {x for x in r["query_domains_after"].split("|") if x}
            self.assertTrue(before_n <= after_n, "%s lost names %s"
                            % (r["company_id"], before_n - after_n))
            self.assertTrue(before_d <= after_d, "%s lost domains %s"
                            % (r["company_id"], before_d - after_d))

    def test_decision_date_identity_is_always_preserved(self):
        for r in self.rep:
            if r["name_at_decision"]:
                self.assertIn(r["name_at_decision"], r["query_names"].split("|"))
            if r["domain_at_decision"]:
                self.assertIn(r["domain_at_decision"], r["query_domains"].split("|"))

    def test_no_individual_panel_chain_is_claimed_by_two_companies(self):
        """chain_root can hold several merged roots; check each one separately,
        otherwise two companies sharing one root would slip through whenever
        their joined strings happen to differ."""
        seen = {}
        for r in self.rep:
            for root in [x for x in r["chain_root"].split("|") if x]:
                self.assertNotIn(root, seen,
                                 "chain %s claimed by %s and %s"
                                 % (root, seen.get(root), r["company_id"]))
                seen[root] = r["company_id"]

    def test_merged_tiers_agree_with_the_root_count(self):
        for r in self.rep:
            roots = [x for x in r["chain_root"].split("|") if x]
            tiers = [x for x in r["merged_tiers"].split("|") if x]
            self.assertEqual(len(roots), len(tiers), r["company_id"])
            self.assertEqual(int(r["chain_roots_merged"] or 0), len(roots), r["company_id"])
            if tiers:
                self.assertEqual(r["resolution_tier"], tiers[0],
                                 "headline tier must be the strongest accepted one")

    def test_renamed_company_reports_the_NEW_name_as_current_not_the_old_one(self):
        """Regression: resolving only the decision-date slug found the
        pre-rename fragment of the chain and reported "Adagy Robotics" as the
        current name of a company already known to be Tuesday Labs."""
        r = {x["company_id"]: x for x in self.rep}["tuesday-labs"]
        self.assertEqual(r["current_name"], "Tuesday Labs")
        self.assertEqual(r["current_domain"], "tuesdaylabs.com")
        self.assertEqual(int(r["chain_roots_merged"]), 2)
        self.assertEqual(r["merged_tiers"].split("|"), ["T1_SLUG", "T2_CROSSWALK"])
        # both identities observed, oldest first
        self.assertEqual(r["observed_names"].split("|"), ["Adagy Robotics", "Tuesday Labs"])
        self.assertEqual(r["observed_domains"].split("|"),
                         ["adagyrobotics.com", "tuesdaylabs.com"])

    def test_no_company_reports_a_stale_name_as_current(self):
        """The pre-repair current_name came from the live yc-oss record. Where
        both exist they must now agree; a disagreement means the merge missed a
        fragment and we would again be querying sources under a dead name."""
        bad = [(r["company_id"], r["current_name_before"], r["current_name_after"])
               for r in self.ba
               if r["current_name_before"] and r["current_name_after"]
               and r["current_name_before"] != r["current_name_after"]]
        self.assertEqual(bad, [])

    def test_multi_rename_chain_keeps_every_domain_it_ever_published(self):
        r = {x["company_id"]: x for x in self.rep}["feldy"]
        for d in ("aethernrg.com", "aethergtm.com", "tryaether.co", "feldy.ai"):
            self.assertIn(d, r["observed_domains"].split("|"), d)
            self.assertIn(d, r["query_domains"].split("|"), d)
        self.assertEqual(r["current_domain"], "feldy.ai")
        self.assertEqual(r["query_domains"].split("|")[0], "feldy.ai")

    def test_every_resolved_company_carries_evidence(self):
        ev = {r["company_id"] for r in rows(EVIDENCE)}
        for r in self.rep:
            if r["resolution_tier"] != "UNRESOLVED":
                self.assertTrue(r["evidence_key"], "%s has no evidence key" % r["company_id"])
                self.assertTrue(r["evidence_snapshot"], "%s has no snapshot" % r["company_id"])
                self.assertIn(r["company_id"], ev)

    def test_unresolved_rows_state_a_reason_and_keep_old_identifiers(self):
        unres = rows(UNRESOLVED)
        self.assertTrue(unres)
        ids = {r["company_id"] for r in unres}
        for r in unres:
            self.assertTrue(r["unresolved_reason"])
        for r in self.rep:
            if r["company_id"] in ids:
                self.assertEqual(r["resolution_tier"], "UNRESOLVED")
                self.assertEqual(r["current_domain"], "")
                # the old identity must still be queryable
                self.assertTrue(r["query_names"])

    def test_resolved_plus_unresolved_accounts_for_everyone(self):
        n_unres = sum(1 for r in self.rep if r["resolution_tier"] == "UNRESOLVED")
        self.assertEqual(n_unres, len(rows(UNRESOLVED)))
        self.assertEqual(len(self.rep) - n_unres,
                         sum(1 for r in self.rep if r["chain_root"]))

    def test_no_accepted_chain_collides_in_the_real_panel(self):
        panel = Panel(rows(os.path.join(REPO, "data/processed/yc2024_monthly.csv")))
        for r in self.rep:
            if r["chain_root"]:
                self.assertEqual(panel.collision_snapshots(r["chain_root"]), [],
                                 "%s accepted a colliding chain" % r["company_id"])

    def test_collision_guard_fires_on_a_chain_that_does_collide(self):
        """The real panel currently has no over-merged chain, so the guard is
        proved on a synthetic one. Without this the guard could rot unnoticed."""
        synthetic = [
            # two different companies forced into one chain by a shared domain,
            # both present in the same snapshot
            {"batch": "winter-2024", "snapshot": "2025-01-01", "slug": "alpha",
             "name": "Alpha", "website": "https://shared.example"},
            {"batch": "winter-2024", "snapshot": "2025-01-01", "slug": "beta",
             "name": "Beta", "website": "https://shared.example"},
        ]
        p = Panel(synthetic)
        root = p.root_of_key("dom:shared.example")
        self.assertIsNotNone(root)
        self.assertEqual(p.collision_snapshots(root), ["2025-01-01"])

    def test_clean_chain_reports_no_collision(self):
        clean = [
            {"batch": "winter-2024", "snapshot": "2025-01-01", "slug": "solo",
             "name": "Solo", "website": "https://solo.example"},
            {"batch": "winter-2024", "snapshot": "2025-02-01", "slug": "solo",
             "name": "Solo", "website": "https://solo.example"},
        ]
        p = Panel(clean)
        root = p.root_of_key("slug:solo")
        self.assertEqual(p.collision_snapshots(root), [])
        self.assertEqual(len(p.history(root)), 2)


class TestNoAmountsAndNothingFrozenTouched(unittest.TestCase):

    def test_no_output_column_holds_an_amount(self):
        pat = re.compile(r"amount|usd|eur|size|raised|valuation", re.I)
        for path in (REPAIRED, BEFORE_AFTER, UNRESOLVED, EVIDENCE):
            cols = rows(path)[0].keys() if rows(path) else []
            bad = [c for c in cols if pat.search(c or "")]
            self.assertEqual(bad, [], "%s exposes amount columns %s" % (path, bad))

    def test_manifest_records_zero_api_calls_and_zero_amounts(self):
        m = json.load(io.open(MANIFEST, encoding="utf-8"))
        self.assertEqual(m["external_api_calls"], 0)
        self.assertEqual(m["amounts_written"], 0)
        self.assertIn("UNCONFIRMED", m["amount_policy"])

    def test_frozen_funding_y_v1_is_byte_identical_to_the_manifest_record(self):
        m = json.load(io.open(MANIFEST, encoding="utf-8"))
        for rel, digest in m["frozen_funding_y_v1_untouched"].items():
            self.assertEqual(lf_sha256(os.path.join(REPO, rel)), digest,
                             "%s changed" % rel)

    def test_repair_module_imports_nothing_that_can_reach_the_network(self):
        """Checked on the parsed import graph, not on prose: the module's own
        docstring legitimately names RecentFunding and WRDS when explaining why
        the repair exists, and a substring scan would flag that as a call."""
        import ast
        path = os.path.join(SRC, "repair_company_identifiers.py")
        tree = ast.parse(io.open(path, encoding="utf-8").read())
        imported = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        banned = {"requests", "urllib", "http", "socket", "ssl", "ftplib",
                  "httpx", "aiohttp", "subprocess", "sources"}
        self.assertEqual(imported & banned, set(),
                         "repair must be offline; it imports %s" % (imported & banned))

    def test_repair_opens_no_file_for_writing_outside_its_output_directory(self):
        """Every write target must be derived from the output directory."""
        import ast
        path = os.path.join(SRC, "repair_company_identifiers.py")
        src = io.open(path, encoding="utf-8").read()
        tree = ast.parse(src)
        writes = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            is_open = (isinstance(fn, ast.Name) and fn.id == "open") or \
                      (isinstance(fn, ast.Attribute) and fn.attr == "open")
            if not is_open:
                continue
            mode = node.args[1].value if (len(node.args) > 1
                                          and isinstance(node.args[1], ast.Constant)) else ""
            if "w" not in str(mode) and "a" not in str(mode):
                continue
            writes += 1
            target = ast.unparse(node.args[0])
            self.assertTrue(("out_dir" in target) or ("mpath" in target) or (target == "path"),
                            "write target %r is not inside the output directory" % target)
        self.assertGreaterEqual(writes, 2, "expected the repair to write files")

    def test_no_protected_path_is_ever_a_write_target(self):
        src = io.open(os.path.join(SRC, "repair_company_identifiers.py"),
                      encoding="utf-8").read()
        for protected in ("results/verified", "data/processed"):
            for m in re.finditer(re.escape(protected), src):
                line = src[src.rfind("\n", 0, m.start()) + 1:
                           src.find("\n", m.start())]
                self.assertNotIn('"w"', line,
                                 "protected path opened for writing: %s" % line.strip())


class TestDeterminism(unittest.TestCase):

    def test_rerun_is_byte_identical(self):
        before = {p: hashlib.sha256(open(p, "rb").read()).hexdigest()
                  for p in (REPAIRED, BEFORE_AFTER, UNRESOLVED, EVIDENCE, MANIFEST)}
        r = subprocess.run([sys.executable,
                            os.path.join(SRC, "repair_company_identifiers.py"),
                            "--repo", REPO],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr[-800:])
        for p, h in before.items():
            self.assertEqual(hashlib.sha256(open(p, "rb").read()).hexdigest(), h,
                             "%s is not reproducible" % os.path.basename(p))


if __name__ == "__main__":
    unittest.main(verbosity=2)

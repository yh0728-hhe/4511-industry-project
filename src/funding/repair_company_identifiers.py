# -*- coding: utf-8 -*-
"""Offline repair of the per-company query identifier set. ZERO external API calls.

WHY THIS EXISTS
    `build_company_identifiers.py` takes `current_name` / `current_domain` from
    `w24_raw_outcomes_24m.csv`, which in turn takes them from
    `w24_crosswalk.csv`. Wherever the crosswalk failed, both fields are BLANK,
    so the query set contains only the 2024-03-25 identifiers - even when our
    own panel has held the post-rename name and domain for two years.

    Proven cost, not a hypothetical: RM-agenthub was queried as "AgentHub" and
    returned COMPANY_NOT_FOUND, while the already-cached RecentFunding roster
    held `gumloop` with total_raised 70,600,000. RM-delve is still queried as
    `getdelve.com` although the panel has published `delve.co` since the
    2025-01-01 snapshot.

WHAT THIS DOES
    Rebuilds each company's query identifiers from the entity chain in our own
    committed panel, and records, for every cross-identifier link it asserts,
    the evidence that justifies it: which key matched, in which snapshot, from
    which file. Old names and old domains are PRESERVED, never replaced.

WHAT THIS REFUSES TO DO
    No fuzzy name matching. No edit distance, no token overlap, no substring,
    no "best" candidate. Every link is an exact match on a normalised key, and
    any ambiguity is REFUSED and listed as unresolved rather than guessed.

    Two independent guards:
      * a chain holding two records in one snapshot is two companies - refused;
      * a chain root may be claimed by at most one cohort company - if two
        claim it, BOTH are refused.

TIERS, strongest first
    T1_SLUG / T1_DOMAIN / T1_NAME
        The decision-date slug, domain or exact normalised name is present in
        the panel. The chain it belongs to is this company's history.
    T2_CROSSWALK
        The committed `w24_crosswalk.csv` already asserts this link and states
        its method in its own `method` column - for 53 companies that method is
        `former_name`, i.e. the live yc-oss record for the new slug declares the
        2024 name in its `former_names` field. That is a first-party alias
        declaration, not an inference of ours, and discarding it would LOSE
        resolution the existing pipeline already had (Corefin -> adapted,
        DaLMatian -> fractal-labs, Okapi -> tesseral, and 50 more).
        Former-name bridging is also what once falsely merged Ecliptor with
        Hatchet, Forge Rewards with Forge and Lumona with Scout, so the two
        guards below apply to this tier in full.
    T3_ONELINER
        No decision-date identifier appears in the panel and the crosswalk has
        nothing either, because name, slug AND domain changed inside the
        190-day gap between the 2024-03-25 cohort file and the earliest panel
        snapshot (2024-10-01). The bridge is an EXACT one-liner /
        short-description string match, accepted only when the string
        identifies exactly one unclaimed panel chain AND exactly one cohort
        company. This is what links AgentHub to Gumloop.
    UNRESOLVED
        Everything else, with a stated reason.

READS (all committed, read-only)
    data/processed/w24_spreadsheet_2024-03-25.csv
    data/processed/yc2024_monthly.csv
    data/processed/w24_crosswalk.csv
    data/processed/w24_raw_outcomes_24m.csv

WRITES (new files only)
    data/interim/identifier_repair/company_identifiers_repaired.csv
    data/interim/identifier_repair/identifier_repair_before_after.csv
    data/interim/identifier_repair/identifier_repair_unresolved.csv
    data/interim/identifier_repair/identifier_repair_evidence.csv
    data/interim/identifier_repair/identifier_repair_manifest.json

NEVER WRITES
    results/verified/funding_y_v1/**  - the frozen Funding Y v1
    data/processed/**                 - the validated inputs
    Nothing here creates, changes or implies any funding label.
"""

import argparse
import csv
import hashlib
import io
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from entity_resolution.normalize import norm_domain, norm_name, yc_slug  # noqa: E402

OUT_DIR = os.path.join("data", "interim", "identifier_repair")

REPAIRED_COLS = [
    "company_id",
    # preserved decision-date identity - never overwritten
    "name_at_decision", "domain_at_decision", "slug_at_decision",
    # resolved current identity, from our own panel
    "current_name", "current_domain", "current_slug", "current_obs_snapshot",
    # every identity the chain ever published, oldest first
    "observed_names", "observed_domains", "observed_slugs",
    # the query sets a source lookup should use
    "query_names", "query_domains",
    # provenance
    "resolution_tier", "merged_tiers", "evidence_key", "evidence_snapshot",
    "evidence_source", "chain_root", "chain_roots_merged", "chain_snapshot_count",
    "refused_links", "renamed_observed", "unresolved_reason",
]

BEFORE_AFTER_COLS = [
    "company_id", "name_at_decision",
    "current_name_before", "current_name_after",
    "current_domain_before", "current_domain_after",
    "query_names_before", "query_names_after",
    "query_domains_before", "query_domains_after",
    "in_yc_directory_before", "chain_resolved_after",
    "resolution_tier", "changed",
]

UNRESOLVED_COLS = ["company_id", "name_at_decision", "domain_at_decision",
                   "slug_at_decision", "oneliner_at_decision",
                   "unresolved_reason", "detail"]

EVIDENCE_COLS = ["company_id", "link_asserted", "evidence_type", "evidence_value",
                 "evidence_snapshot", "evidence_source", "verifiable_by"]


def lf_sha256(path):
    """SHA-256 of the LF-normalised bytes, so a CRLF checkout hashes the same."""
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read().replace(b"\r\n", b"\n")).hexdigest()


def norm_oneliner(s):
    """Exact-comparison key for a short description. NOT a fuzzy matcher.

    Lowercases, collapses whitespace and drops trailing punctuation only.
    Nothing is stemmed, truncated or reordered, so two different descriptions
    can never collide into one key.
    """
    s = (s or "").strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s.rstrip(" .!,;:")


def is_truncated(s):
    """yc-oss truncates long one-liners; a truncated string is not evidence."""
    return "…" in (s or "") or (s or "").rstrip().endswith("...")


def domain_contradicts(query_domains, candidate_domain):
    """True when a candidate must be REFUSED because its domain is not ours.

    This is the rule already applied at run_recentfunding_benchmark.py:201,
    lifted into a named, testable function so the Preqin matcher can reuse the
    identical test instead of reimplementing it. It is what stops a same-name
    company being accepted: our Lantern is lantern.dev, the source's only
    Lantern is lanternhq.com, so that candidate is refused.

    Returns False when we hold no domain at all - absence of a domain is not
    evidence against a candidate, it just means the name is all we have and the
    caller must treat the match as unverified rather than accepted.

    >>> domain_contradicts(["delve.co", "getdelve.com"], "delve.bio")
    True
    >>> domain_contradicts(["delve.co", "getdelve.com"], "delve.co")
    False
    >>> domain_contradicts([], "anything.com")
    False
    """
    ours = {norm_domain(d) for d in (query_domains or []) if norm_domain(d)}
    cand = norm_domain(candidate_domain)
    if not ours or not cand:
        return False
    return cand not in ours


def read_csv(path):
    return list(csv.DictReader(io.open(path, encoding="utf-8-sig")))


def ordered_unique(items):
    out, seen = [], set()
    for x in items:
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


class Panel(object):
    """Union-find entity chains over the committed winter-2024 panel."""

    def __init__(self, rows):
        self.rows = [r for r in rows if r.get("batch") == "winter-2024"]
        self.parent = {}
        for r in self.rows:
            ks = self.keys_of(r)
            for k in ks[1:]:
                self.union(ks[0], k)
        self.chain = {}
        for r in self.rows:
            ks = self.keys_of(r)
            if ks:
                self.chain.setdefault(self.find(ks[0]), {}) \
                          .setdefault(r["snapshot"], []).append(r)

    @staticmethod
    def keys_of(r):
        ks = []
        if r.get("slug"):
            ks.append("slug:" + r["slug"].lower())
        d = norm_domain(r.get("website"))
        if d:
            ks.append("dom:" + d)
        n = norm_name(r.get("name"))
        if n:
            ks.append("nm:" + n)
        return ks

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb

    def root_of_key(self, key):
        return self.find(key) if key in self.parent else None

    def collision_snapshots(self, root):
        return sorted(sn for sn, rs in self.chain.get(root, {}).items() if len(rs) > 1)

    def history(self, root):
        """Chain records, oldest snapshot first."""
        return [(sn, self.chain[root][sn][0]) for sn in sorted(self.chain.get(root, {}))]

TIER_RANK = {"T1_SLUG": 0, "T1_DOMAIN": 1, "T1_NAME": 2, "T2_CROSSWALK": 3,
             "T3_ONELINER": 4}


def candidate_keys(panel, slug_dec, dom_dec, name_dec, xw):
    """Every identifier that could point at this company's panel history.

    ORDERED, strongest first. ALL resolving keys are returned, not just the
    first: a rename can change slug, domain and name at once, so the
    decision-date slug and the crosswalk's current slug can land on two
    DIFFERENT fragments of the same company's history. Taking only the first
    hit reported the pre-rename fragment as the current identity - it labelled
    "Adagy Robotics" as the current name of a company the crosswalk already
    knew had become Tuesday Labs, for 35 companies. Merging every candidate is
    what build_raw_outcomes.chain_for does, and this mirrors it deliberately.
    """
    attempts = [("T1_SLUG", "slug:" + (slug_dec or "").lower(), slug_dec),
                ("T1_DOMAIN", "dom:" + norm_domain(dom_dec), norm_domain(dom_dec)),
                ("T1_NAME", "nm:" + norm_name(name_dec), norm_name(name_dec))]
    matched = (xw.get("matched_slug") or "").strip().lower()
    method = (xw.get("method") or "").strip()
    if matched and method not in ("", "UNMATCHED"):
        attempts.append(("T2_CROSSWALK", "slug:" + matched,
                         "crosswalk:%s=%s" % (method, matched)))
    out, seen = [], set()
    for tier, key, shown in attempts:
        if not shown:
            continue
        root = panel.root_of_key(key)
        if root is None or root not in panel.chain or root in seen:
            continue
        seen.add(root)
        out.append((tier, shown if tier == "T2_CROSSWALK" else key, root))
    return out


def merge_roots(panel, cands):
    """Merge candidate chains, refusing any that puts 2 records in one snapshot.

    Returns (accepted, refused); accepted is [(tier, key, root)] in tier order.
    The clash test is the collision guard that stopped Ecliptor merging with
    Hatchet, Forge Rewards with Forge and Lumona with Scout. It applies to
    every tier, including the crosswalk's own former-name link.
    """
    accepted, refused, occupied = [], [], {}
    for tier, key, root in cands:
        internal = panel.collision_snapshots(root)
        if internal:
            refused.append("%s via %s: chain is internally over-merged at %s"
                           % (root, key, internal[0]))
            continue
        clash = sorted(sn for sn in panel.chain[root] if sn in occupied)
        if clash and accepted:
            refused.append("%s via %s: snapshot clash with an accepted chain at %s"
                           % (root, key, clash[0]))
            continue
        for sn in panel.chain[root]:
            occupied[sn] = root
        accepted.append((tier, key, root))
    return accepted, refused


def merged_history(panel, roots):
    """Records of all merged chains, oldest snapshot first, deduplicated."""
    seen, hist = set(), []
    for root in roots:
        for sn, row in panel.history(root):
            marker = (sn, row.get("slug"), row.get("name"), row.get("website"))
            if marker in seen:
                continue
            seen.add(marker)
            hist.append((sn, row))
    hist.sort(key=lambda t: t[0])
    return hist


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--repo", default=".")
    args = ap.parse_args()
    repo = os.path.abspath(args.repo)

    p_sheet = os.path.join(repo, "data/processed/w24_spreadsheet_2024-03-25.csv")
    p_panel = os.path.join(repo, "data/processed/yc2024_monthly.csv")
    p_cross = os.path.join(repo, "data/processed/w24_crosswalk.csv")
    p_out24 = os.path.join(repo, "data/processed/w24_raw_outcomes_24m.csv")
    out_dir = os.path.join(repo, OUT_DIR)
    os.makedirs(out_dir, exist_ok=True)

    sheet = read_csv(p_sheet)
    panel = Panel(read_csv(p_panel))
    outcomes = read_csv(p_out24)
    crosswalk = {r["sheet_name"]: r for r in read_csv(p_cross)}

    sheet_by_name = {}
    for s in sheet:
        sheet_by_name[s.get("Company Name", "").strip()] = s

    say = lambda *a: print(*a)
    say("panel: %d winter-2024 rows -> %d entity chains" % (len(panel.rows), len(panel.chain)))
    say("cohort: %d companies" % len(outcomes))

    # ---- phase A: collect every candidate chain for every company -----------
    recs = []
    for r in outcomes:
        name_dec = r["name_at_decision"]
        s = sheet_by_name.get(name_dec.strip(), {})
        recs.append({
            "company_id": r["entity_id"], "name_at_decision": name_dec,
            "domain_at_decision": norm_domain(r["domain_at_decision"]
                                              or s.get("Company Website", "")),
            "slug_at_decision": yc_slug(s.get("YC Link", "")),
            "oneliner_at_decision": s.get("Short Description", ""),
            "in_yc_directory_before": r["in_yc_directory_at_cutoff"],
            "current_name_before": r["current_name"],
            "current_domain_before": r["current_domain"],
            "former_names_before": r["former_names"],
            "cands": [], "accepted": [], "refused": [],
            "tier": None, "key": None, "roots": [],
            "unresolved_reason": "", "detail": "", "evidence_snapshot": "",
        })
    for rec in recs:
        rec["cands"] = candidate_keys(
            panel, rec["slug_at_decision"], rec["domain_at_decision"],
            rec["name_at_decision"], crosswalk.get(rec["name_at_decision"]) or {})

    # ---- phase B: a panel chain belongs to exactly ONE company --------------
    # Two companies wanting one chain means at least one link is wrong. The
    # chain goes to the company holding the STRONGEST candidate tier for it; an
    # exact tie is genuinely undecidable and is refused for both, not guessed.
    wanted = {}
    for rec in recs:
        for tier, key, root in rec["cands"]:
            wanted.setdefault(root, []).append((TIER_RANK[tier], rec["company_id"]))
    owner_of, contested = {}, {}
    for root, bids in wanted.items():
        best = min(b[0] for b in bids)
        top = sorted({cid for rank, cid in bids if rank == best})
        if len(top) == 1:
            owner_of[root] = top[0]
        else:
            contested[root] = top
    for rec in recs:
        kept = []
        for tier, key, root in rec["cands"]:
            if root in contested:
                rec["refused"].append("%s via %s: contested at the same tier by %s"
                                      % (root, key, ",".join(contested[root])))
            elif owner_of.get(root) != rec["company_id"]:
                rec["refused"].append("%s via %s: belongs to %s on a stronger key"
                                      % (root, key, owner_of.get(root)))
            else:
                kept.append((tier, key, root))
        rec["cands"] = kept

    # ---- phase C: merge each company's own chains, with the clash guard -----
    for rec in recs:
        accepted, refused = merge_roots(panel, rec["cands"])
        rec["accepted"] = accepted
        rec["roots"] = [root for _, _, root in accepted]
        rec["refused"].extend(refused)
        if accepted:
            rec["tier"], rec["key"] = accepted[0][0], accepted[0][1]

    claimed = {root for rec in recs for root in rec["roots"]}

    # ---- phase D: tier 3, the exact one-liner bridge, for what is left ------
    ol_to_roots = {}
    for root in panel.chain:
        if root in claimed or panel.collision_snapshots(root):
            continue
        for sn, row in panel.history(root):
            ol = row.get("one_liner", "")
            if ol and not is_truncated(ol):
                k = norm_oneliner(ol)
                if k:
                    ol_to_roots.setdefault(k, {}).setdefault(root, sn)

    need = [rec for rec in recs if not rec["roots"]]
    ol_to_cohort = {}
    for rec in need:
        k = norm_oneliner(rec["oneliner_at_decision"])
        if k:
            ol_to_cohort.setdefault(k, []).append(rec["company_id"])

    for rec in need:
        k = norm_oneliner(rec["oneliner_at_decision"])
        if not k:
            rec.update(unresolved_reason="NO_ONELINER",
                       detail="no short description at the decision date")
            continue
        roots = ol_to_roots.get(k, {})
        if not roots:
            rec.update(unresolved_reason="NO_PANEL_MATCH",
                       detail="no decision-date identifier, no crosswalk link, and no "
                              "unclaimed chain ever published this exact description")
            continue
        if len(roots) > 1:
            rec.update(unresolved_reason="ONELINER_AMBIGUOUS_PANEL",
                       detail="%d unclaimed chains share this description: %s"
                              % (len(roots), ",".join(sorted(roots)[:3])))
            continue
        if len(ol_to_cohort.get(k, [])) > 1:
            rec.update(unresolved_reason="ONELINER_AMBIGUOUS_COHORT",
                       detail="%d cohort companies share this description: %s"
                              % (len(ol_to_cohort[k]), ",".join(sorted(ol_to_cohort[k]))))
            continue
        root = list(roots)[0]
        if root in claimed:
            rec.update(unresolved_reason="ROOT_CONTESTED",
                       detail="chain %s was claimed while bridging" % root)
            continue
        rec.update(tier="T3_ONELINER", key="oneliner:" + k, roots=[root],
                   accepted=[("T3_ONELINER", "oneliner:" + k, root)],
                   evidence_snapshot=roots[root])
        claimed.add(root)

    for rec in recs:
        if not rec["roots"] and not rec["unresolved_reason"]:
            rec.update(unresolved_reason="NO_PANEL_MATCH",
                       detail="no candidate identifier resolved to a panel chain")

    # ---------------- build the repaired identifier sets ---------------------
    repaired, before_after, unresolved, evidence = [], [], [], []
    for rec in recs:
        cid = rec["company_id"]
        names_before = ordered_unique(
            [rec["current_name_before"], rec["name_at_decision"]]
            + [f for f in (rec["former_names_before"] or "").split("|") if f])
        doms_before = ordered_unique([norm_domain(rec["current_domain_before"]),
                                      rec["domain_at_decision"]])

        obs_names, obs_doms, obs_slugs = [], [], []
        cur_name = cur_dom = cur_slug = cur_snap = ""
        snap_count = 0
        ev_snap = rec.get("evidence_snapshot", "")

        if rec["roots"]:
            hist = merged_history(panel, rec["roots"])
            snap_count = len({sn for sn, _ in hist})
            for sn, row in hist:
                if row.get("name"):
                    obs_names.append(row["name"].strip())
                d = norm_domain(row.get("website"))
                if d:
                    obs_doms.append(d)
                if row.get("slug"):
                    obs_slugs.append(row["slug"].lower())
            obs_names, obs_doms, obs_slugs = (ordered_unique(obs_names),
                                              ordered_unique(obs_doms),
                                              ordered_unique(obs_slugs))
            # the LAST NON-EMPTY value, not the last snapshot's: a dormant or
            # delisted record can carry a blank website, and taking it verbatim
            # would blank out a domain the chain demonstrably published earlier.
            for sn, row in reversed(hist):
                if not cur_name and (row.get("name") or "").strip():
                    cur_name, cur_snap = row["name"].strip(), sn
                if not cur_dom and norm_domain(row.get("website")):
                    cur_dom = norm_domain(row["website"])
                    cur_snap = cur_snap or sn
                if not cur_slug and (row.get("slug") or "").strip():
                    cur_slug = row["slug"].strip().lower()
                if cur_name and cur_dom and cur_slug:
                    break
            cur_snap = cur_snap or hist[-1][0]
            if not ev_snap:
                ev_snap = hist[0][0]

            # one evidence row per ACCEPTED link, so every asserted connection
            # across a name, slug or domain change can be checked individually
            for tier, key, root in rec["accepted"]:
                src = "data/processed/yc2024_monthly.csv"
                if tier == "T2_CROSSWALK":
                    src += "; data/processed/w24_crosswalk.csv"
                    how = ("grep %r in w24_crosswalk.csv, then grep its matched_slug "
                           "in the panel" % rec["name_at_decision"])
                elif tier == "T3_ONELINER":
                    src += "; data/processed/w24_spreadsheet_2024-03-25.csv"
                    how = "grep the exact description string in both files"
                else:
                    how = "grep %s in the panel" % key.split(":", 1)[-1]
                evidence.append({
                    "company_id": cid,
                    "link_asserted": "%s <-> panel chain %s"
                                     % (rec["name_at_decision"], root),
                    "evidence_type": tier,
                    "evidence_value": key,
                    "evidence_snapshot": ev_snap,
                    "evidence_source": src,
                    "verifiable_by": how,
                })
        else:
            unresolved.append({
                "company_id": cid, "name_at_decision": rec["name_at_decision"],
                "domain_at_decision": rec["domain_at_decision"],
                "slug_at_decision": rec["slug_at_decision"],
                "oneliner_at_decision": rec["oneliner_at_decision"],
                "unresolved_reason": rec["unresolved_reason"] or "NO_PANEL_MATCH",
                "detail": rec["detail"],
            })

        # Query sets: newest panel identity first, then whatever the pipeline
        # already held, then the decision-date identity, then declared former
        # names. The pre-repair values are appended UNCONDITIONALLY so the
        # repair can only ever ADD candidates - never drop one. yc-oss's live
        # `name` and the panel's `name` can disagree ("Tuesday Labs" vs
        # "Tuesday Lab"), and a lookup should be allowed to try both.
        q_names = ordered_unique(list(reversed(obs_names))
                                 + [rec["current_name_before"],
                                    rec["name_at_decision"]]
                                 + [f for f in (rec["former_names_before"] or "").split("|") if f])
        q_doms = ordered_unique(list(reversed(obs_doms))
                                + [norm_domain(rec["current_domain_before"]),
                                   rec["domain_at_decision"]])

        repaired.append({
            "company_id": cid,
            "name_at_decision": rec["name_at_decision"],
            "domain_at_decision": rec["domain_at_decision"],
            "slug_at_decision": rec["slug_at_decision"],
            "current_name": cur_name, "current_domain": cur_dom,
            "current_slug": cur_slug, "current_obs_snapshot": cur_snap,
            "observed_names": "|".join(obs_names),
            "observed_domains": "|".join(obs_doms),
            "observed_slugs": "|".join(obs_slugs),
            "query_names": "|".join(q_names),
            "query_domains": "|".join(q_doms),
            "resolution_tier": rec["tier"] or "UNRESOLVED",
            "evidence_key": rec["key"] or "",
            "evidence_snapshot": ev_snap,
            "evidence_source": "data/processed/yc2024_monthly.csv" if rec["roots"] else "",
            "chain_root": "|".join(rec["roots"]),
            "chain_roots_merged": len(rec["roots"]),
            "merged_tiers": "|".join(t for t, _, _ in rec["accepted"]),
            "refused_links": " ; ".join(rec["refused"]),
            "chain_snapshot_count": snap_count,
            "renamed_observed": "YES" if (cur_name and norm_name(cur_name)
                                          != norm_name(rec["name_at_decision"])) else "NO",
            "unresolved_reason": rec["unresolved_reason"],
        })

        before_after.append({
            "company_id": cid, "name_at_decision": rec["name_at_decision"],
            "current_name_before": rec["current_name_before"], "current_name_after": cur_name,
            "current_domain_before": norm_domain(rec["current_domain_before"]),
            "current_domain_after": cur_dom,
            "query_names_before": "|".join(names_before),
            "query_names_after": "|".join(q_names),
            "query_domains_before": "|".join(doms_before),
            "query_domains_after": "|".join(q_doms),
            "in_yc_directory_before": rec["in_yc_directory_before"],
            "chain_resolved_after": "YES" if rec["roots"] else "NO",
            "resolution_tier": rec["tier"] or "UNRESOLVED",
            "changed": "YES" if ("|".join(names_before) != "|".join(q_names)
                                 or "|".join(doms_before) != "|".join(q_doms)) else "NO",
        })

    def dump(name, cols, rows_):
        path = os.path.join(out_dir, name)
        with io.open(path, "w", newline="", encoding="utf-8-sig") as fh:
            w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows_)
        say("wrote %s (%d rows)" % (os.path.relpath(path, repo).replace("\\", "/"), len(rows_)))

    dump("company_identifiers_repaired.csv", REPAIRED_COLS, repaired)
    dump("identifier_repair_before_after.csv", BEFORE_AFTER_COLS, before_after)
    dump("identifier_repair_unresolved.csv", UNRESOLVED_COLS, unresolved)
    dump("identifier_repair_evidence.csv", EVIDENCE_COLS, evidence)

    manifest = {
        "generated_for_commit_input": "see git log; this file records INPUT hashes only",
        "external_api_calls": 0,
        "amounts_written": 0,
        "amount_policy": "Preqin amount semantics UNCONFIRMED (WRDS dictionary "
                         "descriptions are all None; vendor glossary pages are "
                         "empty). No amount is recorded anywhere by this repair.",
        "inputs": {p: lf_sha256(os.path.join(repo, p)) for p in [
            "data/processed/w24_spreadsheet_2024-03-25.csv",
            "data/processed/yc2024_monthly.csv",
            "data/processed/w24_crosswalk.csv",
            "data/processed/w24_raw_outcomes_24m.csv",
        ]},
        "frozen_funding_y_v1_untouched": {p: lf_sha256(os.path.join(repo, p)) for p in [
            "results/verified/funding_y_v1/company_labels.csv",
            "results/verified/funding_y_v1/manifest.json",
        ]},
        "counts": {
            "cohort": len(repaired),
            "resolved": sum(1 for r in repaired if r["resolution_tier"] != "UNRESOLVED"),
            "unresolved": len(unresolved),
            "changed": sum(1 for r in before_after if r["changed"] == "YES"),
        },
    }
    mpath = os.path.join(out_dir, "identifier_repair_manifest.json")
    with io.open(mpath, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(manifest, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    say("wrote %s" % os.path.relpath(mpath, repo).replace("\\", "/"))

    from collections import Counter
    say("")
    say("resolution tiers:")
    for t, n in Counter(r["resolution_tier"] for r in repaired).most_common():
        say("   %-16s %3d" % (t, n))
    say("unresolved reasons:")
    for t, n in Counter(r["unresolved_reason"] for r in unresolved).most_common():
        say("   %-26s %3d" % (t, n))
    say("")
    say("current_domain blank before : %d"
        % sum(1 for r in before_after if not r["current_domain_before"]))
    say("current_domain blank after  : %d"
        % sum(1 for r in before_after if not r["current_domain_after"]))
    say("query-set changed           : %d"
        % sum(1 for r in before_after if r["changed"] == "YES"))
    say("companies gaining a domain  : %d"
        % sum(1 for r in before_after
              if not r["current_domain_before"] and r["current_domain_after"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

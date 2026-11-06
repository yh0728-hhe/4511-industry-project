# -*- coding: utf-8 -*-
"""Per-company (240-row) research-gap inventory for Funding Y. OFFLINE.

WHAT THIS IS
    One row per cohort company (all 240), joining ONLY already-committed
    outputs:
        - the frozen Funding Y v1 label (results/verified/funding_y_v1/)
        - the offline identifier repair (data/interim/identifier_repair/)
        - the offline re-match of the 12 repair-affected companies
          (data/interim/rematch_offline/)
        - the CANDIDATE official-announcement evidence supplement
          (data/metadata/funding_supplement/*.json, excluding this script's
          own outputs and manifest.json)
        - the 20-company Historical X pilot selection
          (data/metadata/pilot_20/pilot_20_selection.csv), for prioritisation
          only, not for any label.

    No new source is read, no network/API/model call is made, and no
    existing value is recomputed differently than its own generator already
    computed it -- this script only joins and tags what already exists.

WHY FIVE SEPARATE, OVERLAPPING REASON FLAGS, NOT ONE CATEGORY
    A company can simultaneously (a) carry a frozen UNKNOWN label, (b) have
    a CANDIDATE announcement on file, (c) have unresolved entity identity,
    (d) have an unclosed detail-cache gap, and (e) have zero observed
    events -- RM-agenthub is exactly this case. Collapsing that into one
    mutually-exclusive "reason" would misstate overlapping evidence as a
    single explanation. `reason_flags` is therefore a pipe-joined SET, and
    the boolean columns are independent of each other by construction.

WHAT THIS DOES NOT DO
    - Does not create, change, or promote any Funding Y v1 label. The five
      `frozen_*` columns are read verbatim from company_labels.csv; a test
      recomputes them independently from that same file and asserts byte
      equality. Candidate-evidence presence is recorded alongside the frozen
      label, never merged into it.
    - Does not assert the Lantern or Argon AI Form D matches are false. Both
      carry an existing `funding_match_caveat` in
      data/processed/w24_raw_outcomes_24m.csv (issuer-state mismatch;
      Lantern additionally an inactive-vs-new-filing conflict). That text is
      carried through verbatim as `form_d_confirmed_label_caveat`; this
      script neither invents a third caveat nor concludes the match is
      wrong -- only the project's own prior research log did that reasoning,
      and it is cited, not rederived.
    - Does not call Preqin, WRDS or PitchBook. Their status is reported only
      in `next_source_plan.md`, from the already-committed
      2026-11-05_wrds_funding_source_probe.md log: Preqin deal coverage ends
      2025-03-29 (so it can never establish absence after that date) and its
      amount units are unconfirmed (no amount is read from it here); WRDS
      access itself is unverified from inside this script (no query was
      run); PitchBook was reported unavailable in the account checked.
    - Does not expand matching to the 65-company identifier-defect scope.
      `rematch_offline.py` only ever covered 12 of those; this script reads
      its output, it does not re-run or extend it.

READS (read-only)
    results/verified/funding_y_v1/company_labels.csv
    results/verified/funding_y_v1/manifest.json
    data/processed/w24_raw_outcomes_24m.csv
    data/interim/identifier_repair/identifier_repair_before_after.csv
    data/interim/identifier_repair/identifier_repair_unresolved.csv
    data/interim/rematch_offline/rematch_entity_resolution.csv
    data/interim/rematch_offline/rematch_gaps.csv
    data/metadata/funding_supplement/*.json  (candidate records only)
    data/metadata/pilot_20/pilot_20_selection.csv

WRITES (new files only, this supplement's own directory)
    data/metadata/funding_supplement/research_gap_inventory.csv
    data/metadata/funding_supplement/research_gap_inventory_manifest.json

NEVER WRITES
    results/verified/funding_y_v1/**, data/processed/**, any frozen file,
    or any file outside data/metadata/funding_supplement/.
"""

import argparse
import csv
import glob
import hashlib
import io
import json
import os
import sys

SOURCE_DIR = os.path.join("data", "metadata", "funding_supplement")
OUT_DIR = os.path.join(SOURCE_DIR, "research_gaps")
LABELS_PATH = os.path.join("results", "verified", "funding_y_v1", "company_labels.csv")
Y_MANIFEST_PATH = os.path.join("results", "verified", "funding_y_v1", "manifest.json")
RAW_OUTCOMES_PATH = os.path.join("data", "processed", "w24_raw_outcomes_24m.csv")
REPAIR_BEFORE_AFTER_PATH = os.path.join(
    "data", "interim", "identifier_repair", "identifier_repair_before_after.csv")
REPAIR_UNRESOLVED_PATH = os.path.join(
    "data", "interim", "identifier_repair", "identifier_repair_unresolved.csv")
REMATCH_RES_PATH = os.path.join(
    "data", "interim", "rematch_offline", "rematch_entity_resolution.csv")
REMATCH_GAPS_PATH = os.path.join(
    "data", "interim", "rematch_offline", "rematch_gaps.csv")
PILOT20_PATH = os.path.join("data", "metadata", "pilot_20", "pilot_20_selection.csv")

OUT_FILES = {"research_gap_inventory.csv", "research_gap_inventory_manifest.json"}

ENTITY_UNCERTAIN_STATUSES = ("AMBIGUOUS_MATCH", "COMPANY_NOT_FOUND")

COLUMNS = [
    "company_id", "name_at_decision",
    # (1) frozen label -- read verbatim, never recomputed differently
    "frozen_confirmed_positive", "frozen_observation_status",
    "frozen_observed_event_count", "frozen_recentfunding_status",
    "form_d_confirmed_label_caveat",
    # (2) candidate evidence -- separate layer, does not feed back into (1)
    "candidate_evidence_present", "candidate_event_ids",
    "candidate_identity_status", "candidate_in_window",
    # (3) conservative entity flag, including legacy source-match uncertainty
    "identity_resolution_tier", "identity_chain_resolved",
    "identity_changed_in_repair", "identity_unresolved_reason",
    "rematch_old_status", "rematch_new_status", "rematch_entity_recovered",
    "rematch_funding_evidence_added", "rematch_identity_caveat",
    # (4) missing detail cache -- unclosed, zero-API-call gaps
    "cache_gap_kinds", "cache_how_to_close", "missing_detail_cache",
    # (5) no observed event, derived straight from (1)
    "no_observed_event",
    # cross-cutting
    "entity_uncertain", "in_pilot_20", "reason_flags", "note",
]


def lf_sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read().replace(b"\r\n", b"\n")).hexdigest()


def read_csv(path):
    with io.open(path, encoding="utf-8-sig") as fh:
        return list(csv.DictReader(fh))


def load_candidate_records(repo):
    """Only event files explicitly listed by the approved supplement manifest."""
    records_by_company = {}
    with io.open(os.path.join(repo, SOURCE_DIR, 'manifest.json'), encoding='utf-8') as fh:
        manifest = json.load(fh)
    names = manifest['records']
    if len(names) != len(set(names)):
        raise ValueError('Duplicate candidate record paths')
    for name in sorted(names):
        if os.path.basename(name) != name or '/' in name or '\\' in name or not name.endswith('.json'):
            raise ValueError('Invalid candidate record path')
        path = os.path.join(repo, SOURCE_DIR, name)
        with io.open(path, encoding="utf-8") as fh:
            rec = json.load(fh)
        records_by_company.setdefault(rec["company_id"], []).append((name, rec))
    return records_by_company


def load_pilot20_ids(repo, raw_outcomes_rows):
    """Maps the 20-company pilot selection (by name) to company_id, using
    only the already-committed name_at_decision column -- no new matching
    heuristic, no fuzzy matching. Raises if a pilot name is not found or is
    ambiguous, rather than silently skipping it."""
    by_name = {}
    for row in raw_outcomes_rows:
        by_name.setdefault(row["name_at_decision"].strip(), []).append(row["entity_id"])
    pilot_rows = read_csv(os.path.join(repo, PILOT20_PATH))
    ids = set()
    for p in pilot_rows:
        name = p["company_name"].strip()
        hits = by_name.get(name, [])
        if len(hits) != 1:
            raise ValueError(
                "pilot_20 name %r does not resolve to exactly one company_id "
                "in %s (got %r)" % (name, RAW_OUTCOMES_PATH, hits))
        ids.add(hits[0])
    if len(ids) != 20 or len(pilot_rows) != 20:
        raise ValueError("pilot_20 selection did not resolve to 20 distinct ids")
    return ids


def build_rows(repo):
    labels = read_csv(os.path.join(repo, LABELS_PATH))
    if len(labels) != 240 or len({r['company_id'] for r in labels}) != 240:
        raise ValueError('Expected exactly 240 unique frozen cohort IDs')
    raw_outcomes = {r["entity_id"]: r for r in read_csv(os.path.join(repo, RAW_OUTCOMES_PATH))}
    repair_ba = {r["company_id"]: r for r in read_csv(os.path.join(repo, REPAIR_BEFORE_AFTER_PATH))}
    unresolved = {r["company_id"]: r for r in read_csv(os.path.join(repo, REPAIR_UNRESOLVED_PATH))}
    rematch_res = {r["company_id"]: r for r in read_csv(os.path.join(repo, REMATCH_RES_PATH))}
    gaps_by_company = {}
    for g in read_csv(os.path.join(repo, REMATCH_GAPS_PATH)):
        gaps_by_company.setdefault(g["company_id"], []).append(g)
    candidates = load_candidate_records(repo)
    if set(candidates) - {r['company_id'] for r in labels}:
        raise ValueError('Candidate company outside frozen cohort')
    pilot20_ids = load_pilot20_ids(repo, list(raw_outcomes.values()))

    out_rows = []
    for lab in labels:
        cid = lab["company_id"]
        ro = raw_outcomes.get(cid, {})
        name_at_decision = ro.get("name_at_decision", "")

        frozen_confirmed_positive = lab["confirmed_positive"].strip()
        frozen_observation_status = lab["observation_status"].strip()
        frozen_observed_event_count = lab["observed_event_count"].strip()
        frozen_recentfunding_status = lab["recentfunding_status"].strip()

        raw_caveat = (ro.get("funding_match_caveat") or "").strip()
        form_d_caveat = raw_caveat if (frozen_confirmed_positive == "1" and raw_caveat) else ""

        cand_list = candidates.get(cid, [])
        candidate_event_ids = "|".join(sorted(rec["event_id"] for _, rec in cand_list))
        candidate_identity_status = "|".join(sorted(
            {rec["identity_chain"]["status"] for _, rec in cand_list}))
        candidate_in_window = "|".join(sorted(
            str(rec["window_check"]["in_window"]) for _, rec in cand_list))

        ba = repair_ba.get(cid, {})
        un = unresolved.get(cid, {})
        rm = rematch_res.get(cid, {})
        gaps = gaps_by_company.get(cid, [])

        no_observed_event = frozen_observed_event_count == "0"
        entity_uncertain = bool(
            frozen_recentfunding_status in ENTITY_UNCERTAIN_STATUSES
            or ba.get("resolution_tier") == "UNRESOLVED"
            or un.get("unresolved_reason")
            or (rm.get("identity_caveat") or "").strip()
        )
        candidate_present = bool(cand_list)
        missing_cache = any(g['gap_kind'] == 'DETAIL_NOT_CACHED' for g in gaps)

        reasons = []
        reasons.append(
            "FROZEN_LABEL_CONFIRMED_POSITIVE" if frozen_confirmed_positive == "1"
            else "FROZEN_LABEL_UNKNOWN")
        if form_d_caveat:
            reasons.append("FORM_D_CAVEAT")
        if candidate_present:
            reasons.append("CANDIDATE_EVIDENCE_PRESENT")
        if entity_uncertain:
            reasons.append("ENTITY_UNCERTAIN")
        if missing_cache:
            reasons.append("MISSING_DETAIL_CACHE")
        if any(g['gap_kind'] == 'SEARCH_NOT_CACHED' for g in gaps):
            reasons.append('MISSING_SEARCH_CACHE')
        if no_observed_event:
            reasons.append("NO_OBSERVED_EVENT")

        note = ""
        if candidate_present and no_observed_event:
            note = ("CANDIDATE evidence exists but the frozen v1 label is still "
                    "UNKNOWN/0 events -- the candidate is not merged into the "
                    "frozen label by this or any script.")
        if form_d_caveat:
            note = (note + " " if note else "") + (
                "Confirmed-positive label rests on a Form D match the "
                "project's own prior research flagged with a caveat below; "
                "this inventory carries the caveat forward without "
                "concluding the match is wrong.")

        row = {
            "company_id": cid,
            "name_at_decision": name_at_decision,
            "frozen_confirmed_positive": frozen_confirmed_positive,
            "frozen_observation_status": frozen_observation_status,
            "frozen_observed_event_count": frozen_observed_event_count,
            "frozen_recentfunding_status": frozen_recentfunding_status,
            "form_d_confirmed_label_caveat": form_d_caveat,
            "candidate_evidence_present": "1" if candidate_present else "0",
            "candidate_event_ids": candidate_event_ids,
            "candidate_identity_status": candidate_identity_status,
            "candidate_in_window": candidate_in_window,
            "identity_resolution_tier": ba.get("resolution_tier", ""),
            "identity_chain_resolved": ba.get("chain_resolved_after", ""),
            "identity_changed_in_repair": ba.get("changed", ""),
            "identity_unresolved_reason": un.get("unresolved_reason", ""),
            "rematch_old_status": rm.get("old_match_status", ""),
            "rematch_new_status": rm.get("new_match_status", ""),
            "rematch_entity_recovered": rm.get("entity_recovered", ""),
            "rematch_funding_evidence_added": rm.get("funding_evidence_added", ""),
            "rematch_identity_caveat": (rm.get("identity_caveat") or "").strip(),
            "cache_gap_kinds": "|".join(g["gap_kind"] for g in gaps),
            "cache_how_to_close": "|".join(g["how_to_close"] for g in gaps),
            "missing_detail_cache": '1' if missing_cache else '0',
            "no_observed_event": "1" if no_observed_event else "0",
            "entity_uncertain": "1" if entity_uncertain else "0",
            "in_pilot_20": "1" if cid in pilot20_ids else "0",
            "reason_flags": "|".join(reasons),
            "note": note,
        }
        out_rows.append(row)
    return out_rows, pilot20_ids


def write_csv(path, rows):
    with io.open(path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=COLUMNS)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def write_json(path, obj):
    with io.open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def build_manifest(repo, rows, pilot20_ids):
    inputs = [LABELS_PATH, Y_MANIFEST_PATH, RAW_OUTCOMES_PATH,
              REPAIR_BEFORE_AFTER_PATH, REPAIR_UNRESOLVED_PATH,
              REMATCH_RES_PATH, REMATCH_GAPS_PATH, PILOT20_PATH]
    input_hashes = {}
    for p in inputs:
        full = os.path.join(repo, p)
        input_hashes[p.replace("\\", "/")] = lf_sha256(full)
    source_manifest = os.path.join(repo, SOURCE_DIR, 'manifest.json')
    with io.open(source_manifest, encoding='utf-8') as fh:
        event_names = json.load(fh)['records']
    for full in [source_manifest] + [os.path.join(repo, SOURCE_DIR, n) for n in sorted(event_names)]:
        rel = os.path.relpath(full, repo).replace("\\", "/")
        base = os.path.basename(full)
        if base in ("research_gap_inventory_manifest.json",):
            continue  # this script's own output, not an input to itself
        input_hashes[rel] = lf_sha256(full)

    counts = {
        "cohort": len(rows),
        "frozen_confirmed_positive": sum(1 for r in rows if r["frozen_confirmed_positive"] == "1"),
        "frozen_unknown": sum(1 for r in rows if r["frozen_confirmed_positive"] != "1"),
        "form_d_confirmed_label_caveat": sum(1 for r in rows if r["form_d_confirmed_label_caveat"]),
        "candidate_evidence_present": sum(1 for r in rows if r["candidate_evidence_present"] == "1"),
        "entity_uncertain": sum(1 for r in rows if r["entity_uncertain"] == "1"),
        "missing_detail_cache_present": sum(1 for r in rows if r["missing_detail_cache"] == '1'),
        "no_observed_event": sum(1 for r in rows if r["no_observed_event"] == "1"),
        "in_pilot_20": sum(1 for r in rows if r["in_pilot_20"] == "1"),
        "rows_with_two_or_more_reason_flags": sum(
            1 for r in rows if len(r["reason_flags"].split("|")) >= 2),
    }
    return {
        "generated_by": "src/funding/build_funding_gap_inventory.py",
        "purpose": "AUTO30-MEAL-COVERAGE-RESULT per-company research-gap inventory",
        "window_start_exclusive": "2024-04-04",
        "window_end_inclusive": "2026-04-04",
        "counts": counts,
        "reason_flags_are_non_exclusive": True,
        "explicitly_not_this": [
            "Not a change to Funding Y v1. results/verified/funding_y_v1/ is "
            "untouched by this script (frozen_* columns are read verbatim).",
            "Not a label promotion. candidate_evidence_present never changes "
            "frozen_confirmed_positive / frozen_observation_status for the "
            "same row.",
            "Not an assertion that the Lantern or Argon AI Form D match is "
            "false -- form_d_confirmed_label_caveat carries the project's "
            "existing caveat text forward, it does not resolve it.",
            "Not a Preqin/WRDS/PitchBook query. Zero network/API/model calls "
            "were made by this script; see next_source_plan.md for their "
            "status as reported by the prior offline probe.",
            "Not an expansion beyond the 20-company pilot or the 12 "
            "companies rematch_offline.py already covered.",
        ],
        "network_requests_made": 0,
        "pilot_20_company_ids": sorted(pilot20_ids),
        "input_hashes": input_hashes,
    }


def resolve_confined_out_dir(repo, out_arg):
    confined_root = os.path.realpath(os.path.join(repo, OUT_DIR))
    out_dir = os.path.realpath(os.path.join(repo, out_arg))
    if out_dir != confined_root:
        raise ValueError(
            "--out must resolve to %r (this supplement's own directory); "
            "got %r, which would write outside it" % (confined_root, out_dir))
    return out_dir


def main():
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--repo", default=".")
    ap.add_argument("--out", default=OUT_DIR)
    args = ap.parse_args()
    repo = os.path.abspath(args.repo)
    try:
        out_dir = resolve_confined_out_dir(repo, args.out)
    except ValueError as exc:
        print("ERROR: %s" % exc)
        return 1
    os.makedirs(out_dir, exist_ok=True)

    rows, pilot20_ids = build_rows(repo)
    csv_path = os.path.join(out_dir, "research_gap_inventory.csv")
    write_csv(csv_path, rows)
    print("wrote %s  rows=%d" % (os.path.relpath(csv_path, repo).replace("\\", "/"), len(rows)))

    manifest = build_manifest(repo, rows, pilot20_ids)
    manifest_path = os.path.join(out_dir, "research_gap_inventory_manifest.json")
    write_json(manifest_path, manifest)
    print("wrote %s" % os.path.relpath(manifest_path, repo).replace("\\", "/"))
    print("counts: %s" % manifest["counts"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

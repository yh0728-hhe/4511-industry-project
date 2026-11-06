# -*- coding: utf-8 -*-
"""Build a CANDIDATE official-announcement evidence supplement. OFFLINE.

SCOPE
    Exactly two seed events, both Series A announcements, both from
    coordinator-supplied source notes (retrieved by an external web tool on
    2026-11-05, reported to this script as text, never fetched or archived by
    this script itself):

        Gumloop  (company_id RM-agenthub) - announced 2025-01-10
        Delve    (company_id RM-delve)    - announced 2025-07-22

    Nothing else is seeded. Delve's prior ~$3.3M 2024 round is mentioned in
    the source note with no precise date and is deliberately NOT turned into
    an event here.

WHAT THIS IS
    A CANDIDATE evidence supplement: for each event, publication date,
    this script's own observed/capture date, URL, publisher, the
    coordinator-supplied excerpt (kept separate from) the structured
    transcription, an identity-chain record, an admission status, caveats,
    a window check against the project's existing outcome window, and a
    hash that binds the LOCAL transcription object, not original page bytes.

WHAT THIS IS NOT
    - Not a Funding Y label. `admission_status` is always "CANDIDATE".
      Nothing here is merged into results/verified/funding_y_v1/, and
      freeze_funding_y_v1.py is never invoked by this script.
    - Not a re-fetch. No network module is imported (asserted by a test);
      every source fact traces to a literal string below, cited to the
      coordinator, not to a live request made by this script.
    - Not a legal-closing confirmation. `closing_status` on every record
      says these are ANNOUNCEMENT dates, not proven legal closing dates.
    - Not a currency inference. A '$' symbol alone never sets a currency
      code here. `agenthub_gumloop.json` evidence E4 already shows a
      '$'-style Gumloop figure elsewhere resolving to CAD, not USD -- the
      same company is the cautionary example for why the symbol alone is
      not accepted as currency evidence anywhere in this repository.

IDENTITY
    Gumloop: CONFIRMED, by reference to the already-reviewed
    data/metadata/rename_evidence/agenthub_gumloop.json (RM-agenthub). This
    script reads that file and refuses to run if evidence_all_hold is not
    true; it does not recompute the rename-evidence chain itself. CONFIRMED
    here is a statement about company identity (which cohort entity issued
    this announcement), which is distinct from and does not require
    `official_yc_declaration_present` (G1 stays OPEN in that file).

    Delve: PENDING. The supplied PRNewswire transcription names "Delve", a
    "San Francisco company", but states no domain. Our own panel holds
    getdelve.com (at decision) and delve.co (from 2025-01-01) for RM-delve,
    both San Francisco -- consistent with, but not equivalent to, a domain
    bind. Per task instruction, no domain-binding chain is invented here;
    this stays PENDING, not CONFIRMED.

READS (read-only)
    data/metadata/rename_evidence/agenthub_gumloop.json
    data/processed/w24_spreadsheet_2024-03-25.csv   (Delve domain at decision)
    data/processed/yc2024_monthly.csv               (Delve current domain)

WRITES (new files only, this supplement's own directory)
    data/metadata/funding_supplement/gumloop_2025-01-10_series_a.json
    data/metadata/funding_supplement/delve_2025-07-22_series_a.json
    data/metadata/funding_supplement/manifest.json

NEVER WRITES
    results/verified/funding_y_v1/**, data/processed/**, any frozen file.
"""

import argparse
import csv
import hashlib
import io
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from entity_resolution.normalize import norm_domain  # noqa: E402

OBSERVED_CAPTURE_DATE = "2026-11-05"
RETRIEVED_BY = "coordinator web tool, reported 2026-11-05"
RETRIEVAL_NOTE = (
    "Coordinator-supplied title/author/publisher/date/structured transcription. "
    "This is a dated citation, not a byte-for-byte page archive, and was not "
    "independently fetched by this script."
)

# Matches the project's existing outcome window (src/funding/sources.py,
# src/funding/rematch_offline.py). Duplicated here deliberately, as those
# modules do, with the same comment, so this file has no import-time
# dependency on either.
WINDOW_START = "2024-04-04"   # exclusive
WINDOW_END = "2026-04-04"     # inclusive

OUT_DIR = os.path.join("data", "metadata", "funding_supplement")
RENAME_EVIDENCE_PATH = os.path.join(
    "data", "metadata", "rename_evidence", "agenthub_gumloop.json")
SHEET_PATH = os.path.join("data", "processed", "w24_spreadsheet_2024-03-25.csv")
PANEL_PATH = os.path.join("data", "processed", "yc2024_monthly.csv")

CURRENCY_SYMBOL_ONLY_BASIS = (
    "The source text gives only a '$' figure, with no currency word or ISO "
    "code attached. A bare '$' is not accepted as evidence of a currency "
    "code anywhere in this repository (see agenthub_gumloop.json evidence "
    "E4, where a '$'-style Gumloop figure elsewhere resolved to CAD, not "
    "USD). currency_code therefore stays blank."
)


def lf_sha256(path):
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read().replace(b"\r\n", b"\n")).hexdigest()


def sha256_canonical(obj):
    blob = json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def in_window(date_str):
    if not date_str or len(str(date_str)) < 10:
        return False
    d = str(date_str)[:10]
    return WINDOW_START < d <= WINDOW_END


def read_csv(path):
    return list(csv.DictReader(io.open(path, encoding="utf-8-sig")))


def gumloop_identity_chain(repo):
    """Read-only reference to the already-reviewed rename-evidence chain."""
    path = os.path.join(repo, RENAME_EVIDENCE_PATH)
    rec = json.load(io.open(path, encoding="utf-8"))
    if not rec.get("evidence_all_hold"):
        raise RuntimeError(
            "refusing to mark Gumloop identity CONFIRMED: "
            "agenthub_gumloop.json evidence_all_hold is not true")
    return {
        "status": "CONFIRMED",
        "company_id": rec["company_id"],
        "basis": RENAME_EVIDENCE_PATH.replace("\\", "/") +
                 " (E1-E5, evidence_all_hold=true); read, not recomputed, "
                 "by this script",
        "current_domain": rec["current_domain"],
        "domain_at_decision": rec["domain_at_decision"],
        "note": "CONFIRMED here is an identity claim (which W24 cohort "
                "entity issued this announcement), independent of the "
                "OPEN official-YC-declaration gap (G1) recorded in the "
                "file above. The two must not be conflated: a company "
                "first-party rename statement (E5) is not a YC-issued "
                "declaration.",
    }


def delve_identity_chain(repo):
    """Delve cannot be domain-bound from the supplied source note alone."""
    sheet = read_csv(os.path.join(repo, SHEET_PATH))
    row = next(s for s in sheet if s.get("Company Name", "").strip() == "Delve")
    domain_at_decision = norm_domain(row.get("Company Website"))

    panel = [p for p in read_csv(os.path.join(repo, PANEL_PATH))
             if p.get("slug") == "delve" and p.get("batch") == "winter-2024"]
    panel.sort(key=lambda p: p["snapshot"])
    current_domain = norm_domain(panel[-1].get("website")) if panel else ""
    current_location = next((p.get("locations") for p in reversed(panel)
                             if p.get("locations")), "")

    return {
        "status": "PENDING",
        "company_id": "RM-delve",
        "domain_at_decision": domain_at_decision,
        "current_domain_in_panel": current_domain,
        "current_location_in_panel": current_location,
        "reason": (
            "The PRNewswire release names 'Delve', a 'San Francisco company', "
            "but the supplied transcription states no domain for it. Name + "
            "sector + city overlap with our own RM-delve panel record "
            "(%s, %s) is consistent with, but not equivalent to, a "
            "domain-equivalent bind, and no such chain may be invented. "
            "Marked PENDING, not CONFIRMED." % (current_domain, current_location)
        ),
        "what_would_close_this": (
            "A domain string (e.g. delve.co or getdelve.com) or other "
            "unambiguous identifier inside the release text or its press "
            "contact block; not present in the supplied source note."
        ),
    }


def build_gumloop_record(repo):
    structured_transcription = {
        "company": "Gumloop",
        "round_type": "Series A",
        "lead_investor": "Nexus Venture Partners",
        "participants": ["First Round Capital", "Y Combinator"],
        "summary": "Company announces a $17m Series A led by Nexus Venture "
                   "Partners, with First Round Capital and Y Combinator "
                   "among participants.",
        "cumulative_raised_mentioned": "$20m total raised to date (as of "
                                       "2025-01-10) -- a CUMULATIVE figure, "
                                       "not this event's amount.",
        "currency_code_explicit_in_text": False,
    }
    announced_date = "2025-01-10"
    provenance = {
        "url": "https://www.gumloop.com/blog/gumloops-17m-series-a",
        "publisher": "Gumloop (company blog)",
        "title": "Gumloop's $17m Series A",
        "byline_or_author": "Max Brodeur-Urbas",
        "publication_date": announced_date,
        "observed_capture_date": OBSERVED_CAPTURE_DATE,
        "retrieved_by": RETRIEVED_BY,
        "retrieval_note": RETRIEVAL_NOTE,
        "independent_corroboration": False,
        "independence_note": "Company's own blog; a first-party announcement, "
                             "not independent corroboration of the round.",
    }
    rec = {
        "event_id": "FS-gumloop-2025-01-10-series_a",
        "company_id": "RM-agenthub",
        "company_name_current": "Gumloop",
        "company_name_at_decision": "AgentHub",
        "event_type": "SERIES_A_ANNOUNCEMENT",
        "announced_date": announced_date,
        "closing_status": "ANNOUNCEMENT_ONLY -- treated as an announcement "
                          "date, not a proven legal closing date",
        "provenance": provenance,
        "provided_excerpt": None,
        "structured_transcription": structured_transcription,
        "amount": {
            "as_stated": "$17m",
            "currency_code": None,
            "currency_basis": CURRENCY_SYMBOL_ONLY_BASIS,
            "numeric_value": None,
        },
        "identity_chain": gumloop_identity_chain(repo),
        "admission_status": "CANDIDATE",
        "window_check": {
            "window_start_exclusive": WINDOW_START,
            "window_end_inclusive": WINDOW_END,
            "in_window": in_window(announced_date),
        },
        "caveats": [
            "Not a Funding Y v1 label; CANDIDATE only.",
            "official_yc_declaration_present is false in "
            "agenthub_gumloop.json (G1 OPEN) -- identity here rests on the "
            "company first-party declaration plus independent "
            "corroboration (E3/E4), never on a YC-issued rename record.",
            "Cumulative total_raised ($20m, same page) must not be read as "
            "this event's amount; see agenthub_gumloop.json G3 (OPEN) for "
            "the unreconciled $20m vs cached-roster $70.6m discrepancy.",
            "No dated round-level detail exists in any locally cached "
            "source for Gumloop (agenthub_gumloop.json G2, OPEN); this "
            "record's only basis is the company's own announcement.",
        ],
    }
    rec["hash"] = {
        "algorithm": "sha256",
        "value": sha256_canonical(structured_transcription),
        "binds": "the local structured_transcription object above, NOT the "
                "original page bytes (no page was fetched or archived by "
                "this script)",
    }
    return rec


def build_delve_record(repo):
    structured_transcription = {
        "company": "Delve",
        "round_type": "Series A",
        "lead_investor": "Insight Partners",
        "participants": ["unnamed Fortune 500 CISOs"],
        "summary": "San Francisco company announces a $32M Series A led by "
                   "Insight Partners, with Fortune 500 CISOs participating.",
        "prior_round_mentioned": "Approximately $3.3M in 2024 is mentioned "
                                 "with no precise date; deliberately NOT "
                                 "created as a separate event here.",
        "currency_code_explicit_in_text": False,
    }
    announced_date = "2025-07-22"
    provenance = {
        "url": "https://www.prnewswire.com/news-releases/delve-raises-32m-series-a-to-build-ai-agents-for-compliance-302510121.html",
        "publisher": "PRNewswire (carrying a release issued by Delve)",
        "title": "Delve Raises $32M Series A to Build AI Agents for Compliance",
        "byline_or_author": "news provided by Delve",
        "publication_date": "2025-07-22 09:00 ET",
        "observed_capture_date": OBSERVED_CAPTURE_DATE,
        "retrieved_by": RETRIEVED_BY,
        "retrieval_note": RETRIEVAL_NOTE,
        "independent_corroboration": False,
        "independence_note": "PRNewswire is a wire distributor carrying a "
                             "company-issued release, not an independent "
                             "corroborating source.",
    }
    rec = {
        "event_id": "FS-delve-2025-07-22-series_a",
        "company_id": "RM-delve",
        "company_name_current": "Delve",
        "company_name_at_decision": "Delve",
        "event_type": "SERIES_A_ANNOUNCEMENT",
        "announced_date": announced_date,
        "closing_status": "ANNOUNCEMENT_ONLY -- treated as an announcement "
                          "date, not a proven legal closing date",
        "provenance": provenance,
        "provided_excerpt": None,
        "structured_transcription": structured_transcription,
        "amount": {
            "as_stated": "$32M",
            "currency_code": None,
            "currency_basis": CURRENCY_SYMBOL_ONLY_BASIS,
            "numeric_value": None,
        },
        "identity_chain": delve_identity_chain(repo),
        "admission_status": "CANDIDATE",
        "window_check": {
            "window_start_exclusive": WINDOW_START,
            "window_end_inclusive": WINDOW_END,
            "in_window": in_window(announced_date),
        },
        "caveats": [
            "Not a Funding Y v1 label; CANDIDATE only.",
            "identity_chain.status is PENDING, not CONFIRMED -- this "
            "record must not be read as a verified RM-delve funding event "
            "until a domain or equivalent identifier binds the release to "
            "our panel entity.",
            "Publisher is PRNewswire carrying a company-issued release, "
            "not independent corroboration.",
            "The prior ~$3.3M 2024 round mentioned in the same release has "
            "no precise date and is intentionally not represented as an "
            "event anywhere in this supplement.",
        ],
    }
    rec["hash"] = {
        "algorithm": "sha256",
        "value": sha256_canonical(structured_transcription),
        "binds": "the local structured_transcription object above, NOT the "
                "original page bytes (no page was fetched or archived by "
                "this script)",
    }
    return rec


def build_manifest(repo, records):
    confirmed = sum(1 for r in records if r["identity_chain"]["status"] == "CONFIRMED")
    pending = sum(1 for r in records if r["identity_chain"]["status"] == "PENDING")
    in_window_n = sum(1 for r in records if r["window_check"]["in_window"])
    input_hashes = {}
    for p in (RENAME_EVIDENCE_PATH, SHEET_PATH, PANEL_PATH):
        full = os.path.join(repo, p)
        if os.path.exists(full):
            input_hashes[p.replace("\\", "/")] = lf_sha256(full)
    return {
        "generated_by": "src/funding/build_funding_supplement.py",
        "purpose": "AUTO30-MEAL-EVIDENCE-RESULT CANDIDATE evidence supplement",
        "observed_capture_date": OBSERVED_CAPTURE_DATE,
        "window_start_exclusive": WINDOW_START,
        "window_end_inclusive": WINDOW_END,
        "records": sorted(file_name(r["event_id"]) for r in records),
        "counts": {
            "candidate_announcement_events": len(records),
            "identity_confirmed": confirmed,
            "identity_pending": pending,
            "events_in_outcome_window": in_window_n,
        },
        "explicitly_not_this": [
            "Not Funding Y v1. results/verified/funding_y_v1/ is untouched "
            "by this script.",
            "Not an update to the frozen 53/240 confirmed-positive count, "
            "or the 67 deduplicated events, reported in CURRENT_STATE.md.",
            "No numeric currency amount is confirmed in any record here "
            "(currency_code is null in both).",
            "freeze_funding_y_v1.py was not invoked by this script.",
        ],
        "network_requests_made": 0,
        "input_hashes": input_hashes,
    }


def file_name(event_id):
    assert event_id.startswith("FS-")
    return event_id[len("FS-"):] + ".json"


def write_json(path, obj):
    io.open(path, "w", encoding="utf-8").write(
        json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def resolve_confined_out_dir(repo, out_arg):
    """Resolves --out against --repo and refuses anything that is not
    exactly this supplement's own canonical directory (data/metadata/
    funding_supplement under repo). Raises ValueError rather than letting
    the caller write to wherever the argument happened to point -- this
    script's docstring promises writes stay confined to its own directory,
    and that promise must be enforced, not merely stated."""
    confined_root = os.path.abspath(os.path.join(repo, OUT_DIR))
    out_dir = os.path.abspath(os.path.join(repo, out_arg))
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

    records = [build_gumloop_record(repo), build_delve_record(repo)]

    for rec in records:
        path = os.path.join(out_dir, file_name(rec["event_id"]))
        write_json(path, rec)
        print("wrote %s  identity=%s  in_window=%s" % (
            os.path.relpath(path, repo).replace("\\", "/"),
            rec["identity_chain"]["status"], rec["window_check"]["in_window"]))

    manifest = build_manifest(repo, records)
    write_json(os.path.join(out_dir, "manifest.json"), manifest)
    print("wrote %s" % os.path.relpath(
        os.path.join(out_dir, "manifest.json"), repo).replace("\\", "/"))
    print("counts: %s" % manifest["counts"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

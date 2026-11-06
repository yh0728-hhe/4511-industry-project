# -*- coding: utf-8 -*-
"""Offline validator for data/metadata/funding_supplement/. ZERO API calls.

Checks each CANDIDATE record for: provenance completeness, the excerpt vs
structured-transcription distinction, identity-chain shape, the '$'-alone
currency discipline, the window-check arithmetic, the hash binding note, the
ANNOUNCEMENT_ONLY closing-status discipline, and admission_status. Checks
the whole set for event-id / (company_id, date, event_type) collisions.

This module imports no network-capable module, which a test asserts by
walking its AST, the same way src/funding/rematch_offline.py is checked.
"""

import datetime
import glob
import hashlib
import io
import json
import os
import re

WINDOW_START = "2024-04-04"   # exclusive
WINDOW_END = "2026-04-04"     # inclusive
ISO_CURRENCY_RE = re.compile(r"\b(USD|CAD|EUR|GBP|US dollars?)\b", re.IGNORECASE)
URL_RE = re.compile(r"^https://[A-Za-z0-9.\-]+\.[A-Za-z]{2,}(/\S*)?$")
EVIDENCE_FILE_RE = re.compile(r"([\w./\\-]+\.json)")

# hash.binds must actually DENY binding the original page bytes, not merely
# contain those words -- a false claim like "SHA256 of original page bytes"
# mentions the phrase without denying it, and must still fail.
NEGATES_PAGE_BYTES_RE = re.compile(
    r"\b(not|never|no|n't|excludes?|does\s+not)\b[^.;]{0,80}"
    r"\b(original page|page bytes)\b"
    r"|\b(original page|page bytes)\b[^.;]{0,80}"
    r"\b(not|never|no|n't|excluded|excludes?)\b",
    re.IGNORECASE,
)

REQUIRED_PROVENANCE = ("url", "publisher", "title", "publication_date",
                       "observed_capture_date", "retrieved_by", "retrieval_note")

# Inputs every record here depends on regardless of identity status: the
# cohort spreadsheet and the outcome panel. Duplicated as literal paths
# (matching build_funding_supplement.SHEET_PATH / PANEL_PATH) rather than
# imported, for the same no-generator-dependency reason as lf_sha256 below.
REQUIRED_INPUT_HASH_PATHS = (
    "data/processed/w24_spreadsheet_2024-03-25.csv",
    "data/processed/yc2024_monthly.csv",
)

# Repo root, resolved the same way src/funding/tests/test_funding_supplement.py
# resolves REPO: three dirname() calls up from this file (src/funding/<this> ->
# src/funding -> src -> repo root).
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def _parse_date(date_str):
    """Strict calendar-date parse of the first 10 chars (YYYY-MM-DD).
    Returns a datetime.date, or None if missing, too short, or not a real
    calendar date (e.g. 2025-02-31)."""
    if not date_str or len(str(date_str)) < 10:
        return None
    d = str(date_str)[:10]
    try:
        return datetime.date(int(d[0:4]), int(d[5:7]), int(d[8:10]))
    except (ValueError, TypeError):
        return None


def in_window(date_str):
    d = _parse_date(date_str)
    if d is None:
        return False
    return _parse_date(WINDOW_START) < d <= _parse_date(WINDOW_END)


def sha256_canonical(obj):
    blob = json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


def lf_sha256(path):
    """Mirrors build_funding_supplement.lf_sha256: CRLF-normalized file hash,
    duplicated here deliberately so this module has no import-time dependency
    on the generator."""
    with open(path, "rb") as fh:
        return hashlib.sha256(fh.read().replace(b"\r\n", b"\n")).hexdigest()


def load_records(directory):
    """Returns (records, manifest). Raises if manifest.json is missing."""
    records = []
    for path in sorted(glob.glob(os.path.join(directory, "*.json"))):
        if os.path.basename(path) == "manifest.json":
            continue
        records.append(json.load(io.open(path, encoding="utf-8")))
    manifest_path = os.path.join(directory, "manifest.json")
    manifest = None
    if os.path.exists(manifest_path):
        manifest = json.load(io.open(manifest_path, encoding="utf-8"))
    return records, manifest


def check_provenance(rec):
    issues = []
    prov = rec.get("provenance") or {}
    for field in REQUIRED_PROVENANCE:
        if not str(prov.get(field) or "").strip():
            issues.append("provenance missing/empty field: %s" % field)
    if "independent_corroboration" not in prov:
        issues.append("provenance missing independent_corroboration flag")
    url = prov.get("url")
    if url and not URL_RE.match(str(url)):
        issues.append("provenance.url %r is not a well-formed https URL" % url)
    for date_field in ("publication_date", "observed_capture_date"):
        raw = prov.get(date_field)
        if raw and _parse_date(raw) is None:
            issues.append("provenance.%s %r is not a valid YYYY-MM-DD-prefixed "
                          "calendar date" % (date_field, raw))
    return issues


def check_excerpt_vs_transcription(rec):
    """The two must never be silently merged into one field."""
    issues = []
    if "provided_excerpt" not in rec:
        issues.append("missing provided_excerpt field (must be present, "
                      "even if null)")
    if not rec.get("structured_transcription"):
        issues.append("missing structured_transcription")
    excerpt = rec.get("provided_excerpt")
    transcription = rec.get("structured_transcription")
    if excerpt is not None and excerpt == transcription:
        issues.append("provided_excerpt and structured_transcription are "
                      "identical objects; an exact quote must not be "
                      "relabelled as a paraphrase or vice versa")
    return issues


def check_confirmed_identity_basis(chain):
    """A CONFIRMED identity must cite a real, on-disk, pinned evidence file
    -- not an arbitrary string like 'same name' -- and that file must itself
    say evidence_all_hold=true for the SAME company_id. This is re-derived
    from disk, not trusted from the record's own text."""
    issues = []
    basis = str(chain.get("basis") or "")
    if not basis:
        return ["identity_chain CONFIRMED but no basis cited"]
    match = EVIDENCE_FILE_RE.search(basis)
    if not match:
        return ["identity_chain CONFIRMED basis %r does not cite a checkable "
                "evidence file (expected a *.json path)" % basis]
    rel_path = match.group(1).replace("\\", "/")
    full_path = os.path.join(REPO_ROOT, rel_path)
    if not os.path.isfile(full_path):
        return ["identity_chain CONFIRMED basis cites %r, which does not "
                "exist on disk" % rel_path]
    try:
        evidence = json.load(io.open(full_path, encoding="utf-8"))
    except (ValueError, OSError) as exc:
        return ["identity_chain CONFIRMED basis evidence file %r is not "
                "readable/valid JSON: %s" % (rel_path, exc)]
    if not evidence.get("evidence_all_hold"):
        issues.append("identity_chain CONFIRMED but cited evidence file %r "
                      "has evidence_all_hold=%r, not true"
                      % (rel_path, evidence.get("evidence_all_hold")))
    if evidence.get("company_id") != chain.get("company_id"):
        issues.append("identity_chain CONFIRMED cites evidence file %r for "
                      "company_id %r, but identity_chain.company_id is %r"
                      % (rel_path, evidence.get("company_id"), chain.get("company_id")))
    return issues


def check_identity_chain(rec):
    issues = []
    chain = rec.get("identity_chain") or {}
    status = chain.get("status")
    if status not in ("CONFIRMED", "PENDING"):
        issues.append("identity_chain.status must be CONFIRMED or PENDING, "
                      "got %r" % status)
        return issues
    if not chain.get("company_id"):
        issues.append("identity_chain missing company_id")
    elif chain.get("company_id") != rec.get("company_id"):
        issues.append("identity_chain.company_id (%r) does not match this "
                      "record's company_id (%r)"
                      % (chain.get("company_id"), rec.get("company_id")))
    if status == "CONFIRMED":
        issues += check_confirmed_identity_basis(chain)
    if status == "PENDING" and not chain.get("reason"):
        issues.append("identity_chain PENDING but no reason given")
    return issues


def check_amount_discipline(rec):
    """A bare '$' must never produce a currency_code or numeric_value."""
    issues = []
    amount = rec.get("amount") or {}
    transcription_text = json.dumps(rec.get("structured_transcription") or {})
    has_explicit_currency_word = bool(ISO_CURRENCY_RE.search(transcription_text))
    if amount.get("currency_code") is not None and not has_explicit_currency_word:
        issues.append("currency_code is set (%r) with no explicit currency "
                      "word/code in the transcription -- a bare '$' is not "
                      "sufficient evidence" % amount.get("currency_code"))
    if amount.get("currency_code") is None and amount.get("numeric_value") is not None:
        issues.append("numeric_value is set without a confirmed currency_code")
    if not str(amount.get("as_stated") or "").strip():
        issues.append("amount.as_stated is missing")
    return issues


def check_window(rec):
    issues = []
    announced = rec.get("announced_date")
    if not str(announced or "").strip():
        issues.append("missing announced_date (required on every event, "
                      "regardless of in_window)")
    elif _parse_date(announced) is None:
        issues.append("announced_date %r is not a valid calendar date"
                      % announced)
    wc = rec.get("window_check") or {}
    if wc.get("window_start_exclusive") != WINDOW_START or \
       wc.get("window_end_inclusive") != WINDOW_END:
        issues.append("window_check does not use the project's window "
                      "(%s exclusive .. %s inclusive)" % (WINDOW_START, WINDOW_END))
    expected = in_window(announced)
    if wc.get("in_window") != expected:
        issues.append("window_check.in_window=%r does not match recomputed "
                      "in_window(%r)=%r" % (wc.get("in_window"), announced, expected))
    closing = str(rec.get("closing_status") or "")
    if not closing.startswith("ANNOUNCEMENT_ONLY"):
        issues.append("closing_status must state ANNOUNCEMENT_ONLY -- an "
                      "announced date is not a proven legal closing date")
    return issues


def check_hash(rec):
    issues = []
    h = rec.get("hash") or {}
    if h.get("algorithm") != "sha256":
        issues.append("hash.algorithm must be sha256")
    expected = sha256_canonical(rec.get("structured_transcription") or {})
    if h.get("value") != expected:
        issues.append("hash.value does not match recomputed sha256 of "
                      "structured_transcription (%r != %r)"
                      % (h.get("value"), expected))
    binds = str(h.get("binds") or "")
    mentions_page_bytes = ("page bytes" in binds.lower() or
                          "original page" in binds.lower())
    if not mentions_page_bytes:
        issues.append("hash.binds must state it does NOT bind the original "
                      "page bytes")
    elif not NEGATES_PAGE_BYTES_RE.search(binds):
        issues.append("hash.binds mentions 'original page'/'page bytes' "
                      "but does not explicitly DENY binding them (e.g. "
                      "'SHA256 of original page bytes' affirms a byte-for-"
                      "byte page archive instead of denying one) -- got %r"
                      % binds)
    return issues


def check_admission_status(rec):
    if rec.get("admission_status") != "CANDIDATE":
        return ["admission_status must be CANDIDATE, got %r"
               % rec.get("admission_status")]
    return []


def check_record(rec):
    issues = []
    issues += check_provenance(rec)
    issues += check_excerpt_vs_transcription(rec)
    issues += check_identity_chain(rec)
    issues += check_amount_discipline(rec)
    issues += check_window(rec)
    issues += check_hash(rec)
    issues += check_admission_status(rec)
    if not rec.get("event_id"):
        issues.append("missing event_id")
    if not rec.get("company_id"):
        issues.append("missing company_id")
    return issues


def check_collisions(records):
    """No two records may share an event_id, or a (company, date, type) key."""
    issues = []
    seen_ids = {}
    seen_keys = {}
    for rec in records:
        eid = rec.get("event_id")
        if eid in seen_ids:
            issues.append("duplicate event_id: %r" % eid)
        seen_ids[eid] = seen_ids.get(eid, 0) + 1

        key = (rec.get("company_id"), rec.get("announced_date"), rec.get("event_type"))
        if key in seen_keys:
            issues.append("duplicate (company_id, announced_date, event_type): %r" % (key,))
        seen_keys[key] = seen_keys.get(key, 0) + 1
    return issues


def check_manifest_counts(records, manifest):
    """Counts must be reported separately and must never be, or be mistaken
    for, an update to the overall Funding Y total."""
    issues = []
    if manifest is None:
        return ["manifest.json is missing"]
    counts = manifest.get("counts") or {}
    expected = {
        "candidate_announcement_events": len(records),
        "identity_confirmed": sum(1 for r in records
                                  if r.get("identity_chain", {}).get("status") == "CONFIRMED"),
        "identity_pending": sum(1 for r in records
                                if r.get("identity_chain", {}).get("status") == "PENDING"),
        "events_in_outcome_window": sum(1 for r in records
                                        if r.get("window_check", {}).get("in_window")),
    }
    for k, v in expected.items():
        if counts.get(k) != v:
            issues.append("manifest counts[%r]=%r, expected %r" % (k, counts.get(k), v))
    for forbidden in ("funding_y_total", "updated_funding_y_count",
                     "confirmed_positive_companies", "overall_y_count"):
        if forbidden in manifest or forbidden in counts:
            issues.append("manifest contains %r, which risks being read as "
                          "an update to Funding Y v1's own totals" % forbidden)
    return issues


def required_input_hash_paths(records):
    """The complete set of pinned inputs this supplement's claims depend on:
    the cohort/panel files always, plus the basis evidence file cited by
    every CONFIRMED identity_chain (re-derived the same way
    check_confirmed_identity_basis finds it, not trusted from elsewhere)."""
    required = set(REQUIRED_INPUT_HASH_PATHS)
    for rec in records:
        chain = (rec or {}).get("identity_chain") or {}
        if chain.get("status") != "CONFIRMED":
            continue
        match = EVIDENCE_FILE_RE.search(str(chain.get("basis") or ""))
        if match:
            required.add(match.group(1).replace("\\", "/"))
    return required


def check_manifest_input_hashes(manifest, records):
    """manifest.input_hashes must (a) be independently reproducible from the
    actual pinned files on disk right now, not merely recorded text, and
    (b) actually contain the COMPLETE required set -- dropping the
    rename-evidence or panel hash while keeping an unrelated one (e.g. the
    cohort hash alone) must fail, not silently pass."""
    if manifest is None:
        return []
    issues = []
    input_hashes = manifest.get("input_hashes") or {}
    if not input_hashes:
        issues.append("manifest.input_hashes is missing/empty")
        return issues
    missing = sorted(required_input_hash_paths(records) - set(input_hashes))
    if missing:
        issues.append("manifest.input_hashes is missing required pinned "
                      "input(s) that this supplement's identity claims "
                      "depend on: %r" % missing)
    for rel_path, expected in input_hashes.items():
        full_path = os.path.join(REPO_ROOT, rel_path)
        if not os.path.isfile(full_path):
            issues.append("manifest.input_hashes references %r, which does "
                          "not exist on disk" % rel_path)
            continue
        actual = lf_sha256(full_path)
        if actual != expected:
            issues.append("manifest.input_hashes[%r]=%r does not match the "
                          "recomputed hash %r of the file currently on disk"
                          % (rel_path, expected, actual))
    return issues


def validate_all(directory):
    records, manifest = load_records(directory)
    report = {}
    for rec in records:
        name = rec.get("event_id", "<unknown>")
        issues = check_record(rec)
        if issues:
            report[name] = issues
    collision_issues = check_collisions(records)
    if collision_issues:
        report["<collisions>"] = collision_issues
    manifest_issues = check_manifest_counts(records, manifest)
    manifest_issues += check_manifest_input_hashes(manifest, records)
    if manifest_issues:
        report["<manifest>"] = manifest_issues
    return report


def main():
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    ap.add_argument("--dir", default=os.path.join(
        "data", "metadata", "funding_supplement"))
    args = ap.parse_args()
    report = validate_all(args.dir)
    if not report:
        print("OK: all checks passed, 0 collisions")
        return 0
    for name, issues in report.items():
        print("FAIL %s" % name)
        for issue in issues:
            print("  - %s" % issue)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())

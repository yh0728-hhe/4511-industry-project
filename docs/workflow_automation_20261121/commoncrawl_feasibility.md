# Common Crawl historical source feasibility

## Why this archive was checked

The current workflow lacks enough independently recoverable historical company
context. This probe checked a different public archival dataset rather than
retrying the restricted Wayback endpoint. Common Crawl describes an index of
capture dates and WARC file offsets; its records can be downloaded with HTTP
Range requests. An index hit is a retrieval lead, not readable source evidence.
See the [official index documentation](https://www.commoncrawl.org/cdxj-index)
and [data access documentation](https://www.commoncrawl.org/get-started).

## Selection frozen before company requests

The original March 25 2024 spreadsheet was read as an identity-only list. After
excluding the four previously inspected alphabetically first names, the next
two were AgentHub and Agentic Labs. No outcome labels were joined. The declared
website is a contemporary identity anchor, not proof of legal ownership. Only
the pre-cutoff CC-MAIN-2024-10 collection and exact homepage queries were used;
no domain variants, alternate collections or retry were permitted.

## Observed results on November 27 2026

- AgentHub: index HTTP200, three records returned, two eligible exact-homepage
  HTTP200/text-html pointers dated February23 and March2 2024. No page text was
  recovered from this index response.
- Agentic Labs: index HTTP502. It remains UNKNOWN; no alternate query was tried.
- A separately frozen body request selected AgentHub's latest eligible pointer
  and requested exactly one 3,598-byte range from data.commoncrawl.org. The
  bounded child process timed out after12.884seconds without a complete
  response. No retry or alternate storage host was used.

There were two index-request attempts and one record-request attempt, zero
Claude/model CLI calls for these probes, and zero source facts admitted.
Physical packet/proxy requests remain unknown. The index probe took9.794seconds.
The model-assisted coding task, if completed, is separate engineering work and
is not counted as a company-research model run. No Y or training changed.

## Required gates before any future source admission

A body verifier must bind the requested byte range and archive host, verify the
single decoded WARC response and target URL, reconcile its date with the index
and project cutoff, check payload/block digests and the indexed checksum, and
extract bounded readable text. Unsupported encodings, redirects, conflicting
metadata, oversized content, wrong targets or unreadable text stay held. A
model cannot create the verification record. A page may support an attributed
publisher claim without independently proving its business assertions.

No Common Crawl source has passed these gates in this project. Index parsing is
only a planning capability; it must never generate a proof-ledger entry or be
passed into analysis as page text. Any further real body acquisition needs its
own explicit finite protocol, rather than an automatic retry of this sealed
failure. No new archive provider is enabled in the default workflow.

Evidence files:
`commoncrawl_probe_protocol_20261127.json`,
`commoncrawl_probe_result_20261127.json`,
`commoncrawl_record_protocol_20261127.json`, and
`commoncrawl_record_result_20261127.json`, under
`data/metadata/workflow_20261121/`. Raw index bytes and partial transport output
remain ignored local scratch. These metadata findings do not update X or Y
coverage or establish that either company lacks historical records.

## Offline planning implementation and auditability

`closed_loop.commoncrawl_index.parse_commoncrawl_index` is a pure, bounded
stdlib parser. It validates exact homepage identity, cutoff, SHA1 index digest
syntax, collection-specific file paths, offsets, lengths and overflow. Duplicate
keys, nonfinite JSON, malformed rows and conflicting eligible captures cannot
return partial pointers. Exact duplicate captures are deduplicated. Pointer
objects explicitly deny source admission and require body verification.
The parser performs no retrieval and is not wired into the default workflow.

Fourteen offline regressions passed. Replaying the saved real AgentHub index
response without new requests yields two pointers and rejects the redirect.
Full offline readiness passed all six stages:1,151tests,1,148passed,3skipped.
These are planner/control tests, not a successful WARC body retrieval.

The actual Claude coding attempt timed out after180.927seconds with no returned
files or verdict. Codex implemented and tested the module; no independent Claude
approval is claimed. A separate local auth-status check returned loggedIn=true
with claude.ai auth in0.644seconds. It does not establish provider reachability,
remaining quota or billing. No further inference was requested as a diagnostic.

Exact probe child-source snapshots are stored as non-executable `.py.txt` files
in `probe_worker_sources/` and match the original frozen worker hashes. They
allow inspection of the original bounded requests, not permission to replay a
sealed probe. The raw index response, partial stdout and model prompt remain
private local scratch. The original protocol/result receipts are unchanged.

## A registry lead was held before download

A separate official [PyPI project page](https://pypi.org/project/agenthub-sdk/)
shows four displayed agenthub-sdk releases, all dated September or October2025.
They are after the project cutoff, and the name/domain relationship alone does
not prove identity with the cohort company. The package was not downloaded,
installed or treated as a historical source. No inference is made about deleted
or unavailable older releases. This is a held source lead, not company-outcome
evidence or an agent dependency adopted by this workflow.

## Existing packet reuse was checked separately

The existing 20-company local seed packet file still contains20PENDING packets,
with20observation items and no non-null publication, capture or availability
dates. These are not automatically reusable historical source bodies. In the
older inspected collector, the replay helper returns decoded text/status but
not the response headers/final replay URI needed by the current verifier.
The original raw archive bundle was not located in the bounded roots inspected;
that does not establish global file absence or invalidate the earlier archive
counts. No old probe was rerun. See `local_seed_reuse_audit_20261127.json`.
An optional single-record Muse handoff was drafted privately but not dispatched;
no user action or Muse scheduler is required for the completed offline work.

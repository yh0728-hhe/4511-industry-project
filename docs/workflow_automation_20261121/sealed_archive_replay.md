# Sealed offline archive replay — November 28, 2026

Purpose: reproduce downstream source handling when archive transport is
unavailable, without re-downloading pages or silently querying a current site.
This explicitly enabled library client returns saved HTTPResponse objects only.
The default command remains live process-isolated transport. This module does
not create facts, add trust to arbitrary files, change dates, invoke a model,
or make outcome labels. Existing publisher/identity/temporal checks still run.

A trusted operator prepares a private manifest from an audited earlier
acquisition and independently pins its SHA256. An LLM must not choose its own
trust seal. A self-supplied hash proves file consistency, not HTTPS authenticity,
past public availability, domain ownership or business-claim truth. An unaudited
Muse bundle therefore remains pending; this client cannot promote it by itself.

The manifest schema is exactly version(integer1) and responses(array1..12).
Each response contains exactly request_url, status, response_url, headers,
body_file and body_sha256. URLs must be exact allowed Wayback HTTPS URLs;
response_url must equal request_url and redirects are not followed. body_file is
a simple basename under the manifest root, not an arbitrary path. Manifest and
headers are bounded, duplicate JSON keys and unknown fields are rejected, and
body bytes are re-read and SHA256-checked for every get. At most24explicit local
gets may be configured. Header copies prevent a caller mutating later responses.
Use sequential calls with the shared concurrency1 budget.

Cache miss, changed file, deadline/cap failure or path escape releases no
response. There is no network fallback or implicit retry. Logical search
reservations still count provider get calls; they are not physical HTTP when
this adapter is injected. Consult the client's zero actual_http_requests and
replay events, not a generic injected-runner adapter-call count, to distinguish
replay from acquisition. Deadline callbacks surround bounded local reads; this
is cooperative local-disk checking, not a hard OS disk-I/O deadline.

## Observed real compatibility check

The first integration used two unchanged responses already saved on November25:
a Wayback index and its April2,2024 GitHub Hatchet
snapshot. Existing metadata/body hashes were checked before sealing the new
local manifest. The existing ArchivedPublisherVerifier and TemporalGateway
reconstructed the exact same prior fact ID and text hash,5162characters, with
2local replay gets,0HTTP and0model calls. No new company source, archived page,
financing event or coverage was found. Raw source bytes, headers and manifests
remain in ignored private scratch; only hash/count metadata is shared.

This validates the adapter on an existing development case, not the source's
business assertions, independent editorial quality, model accuracy, predictive
performance or general compatibility. The five additional offline regressions
cover corruption after construction, missing-URL stops, duplicate/unknown keys,
path escapes, response/header ownership, shared deadline and per-get caps.
See sealed_real_archive_replay_result_20261128.json and its final-client
verification sealed_real_archive_replay_final_20261128.json. The final change
adds a get-URL length cap; no source request was repeated.


## Preserving forensic source bytes in Git

Git's automatic newline normalization was observed changing two byte-pinned
forensic script snapshots in committed blobs while local files still matched
their frozen protocol digests. Two exact -text attribute rules now preserve
those bytes, with CR-at-EOL allowed for these data snapshots only. The staged
blobs are verified against the unchanged protocol digests, and one regression
checks actual checkout bytes on both platforms. This is not an assertion that
every older JSON/log has a platform-independent raw-byte hash; original private
run artifacts remain the audit originals. No historical protocol or failed
result was relabelled, and no source/model request was repeated for this fix.

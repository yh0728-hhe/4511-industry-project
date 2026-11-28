# Offline Common Crawl record verification

`verify_commoncrawl_record` prepares a strict-subset body check for a future
independently retrieved Common Crawl record. It performs no HTTP, model calls,
file writes, proof-ledger registration or default workflow configuration change.
No real Common Crawl body has been obtained or validated by this project.

The trusted caller must independently acquire the index and exact archive range
via HTTPS. The verifier revalidates the untrusted capture pointer, checks the
anchored company domain, HTTP206 response URL, byte count and Content-Range, and
bounds gzip decompression. It requires one complete gzip member and one complete
unsegmented WARC response; record type, target URI, record date and content length
must agree. The block SHA1 and payload SHA1 are checked separately and the latter
must match the index. SHA256 identifiers are retained for compressed record,
whole decoded record, HTML and extracted text. SHA1 consistency is not a claim
of collision-resistant authentication.

Only nonchunked, identity-encoded UTF8/ASCII HTML is supported. Redirects,
segmented/truncated/revisit records, unsupported encoding, duplicate critical
headers, extra gzip members and excessive text remain held. The existing static
HTML extraction/headline parser is reused, requiring the declared company name
in a headline. This does not independently establish legal domain ownership or
business claim truth. CSS-computed visibility and JavaScript are not supported.
The WARC date can be subsecond and must agree with the index second while still
falling within the exact project cutoff.

Successful checks return a SourceCandidate, VerifiedRecord and metadata receipt;
they do not register these automatically. The candidate URL is the original
page locator, not newly fetched current text. The archive data URI, exact Range,
record ID and hashes in the receipt must be preserved for source reconstruction.
A source record passing the temporal gateway still cannot release INVEST/PASS
without the separate source-bound claim review. Both decisions were tested and
held as MORE_DILIGENCE / NOT_REVIEWED even after a synthetic archive passed.

This intentionally conservative implementation follows the
[WARC format specification](https://iipc.github.io/warc-specifications/specifications/warc-format/warc-1.1/)
and [Common Crawl index metadata](https://www.commoncrawl.org/cdxj-index).
It is not a general WARC reader, a replacement for warcio, an activated archive
provider, or a compatibility result on real Common Crawl responses. A general
reader should be evaluated separately if unsupported records become available.
No optional dependency was installed or package code executed.

Fourteen focused offline regressions passed. Full private readiness passed all
six stages:1,165tests,1,162passed,3skipped. This is engineering evidence only.
One initial fixture formatting error was corrected without relaxing production
response parsing; all source probes and their failures remain unchanged.
See `data/metadata/workflow_20261121/commoncrawl_record_validation_20261127.json`.

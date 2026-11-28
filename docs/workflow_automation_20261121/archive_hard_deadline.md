# Archive transport hard deadline — November 28, 2026

The single-command discovery workflow and default ArchivedWebsiteProvider now
use IsolatedArchiveHTTPClient. Its
child calls the existing archive-only urllib client with unchanged response,
redirect, identity, date, and content checks. One get means one child and at most
one HTTP request; there is no retry, alternate host, registry fallback or extra
model allowance. Library callers that explicitly inject their own HTTP clients
still own that transport's behavior. The raw ArchiveHTTPClient remains an
internal reusable component; its socket timeout is not a hard overall deadline.

The parent gives ProcessExecutor the current request timeout (already limited
by the shared remaining deadline). DNS, a sequence of connection attempts,
header setup or slow reads cannot leave the child running indefinitely: the
existing process-tree termination mechanism enforces the outer timeout, subject
to operating-system cleanup overhead. If the shared deadline has already
expired it wins; otherwise the run stops ARCHIVE_REQUEST_TIMEOUT. The source
request reservation is retained, no partial response is released and no next
source/model is dispatched as a fallback. This does not guarantee availability.

The runner saves an attempt record before dispatch for both archive and registry
requests. Failed calls update only a sanitized exception type and retain the
prior intent if recording the failure itself fails. Successful body/response
artifacts are unchanged. These are saved application records, not a claim of
crash-proof disk durability or an independent network audit. Both isolation
modules are included in the source fingerprint.

Offline verification includes a real Python child sleeping for 60 seconds,
stopped by the configured 0.3-second deadline without an HTTP request. Injected
composition verifies that one timed-out source yields MORE_DILIGENCE, preserves
the failed attempt, admits zero facts and starts no second HTTP attempt.
Additional checks cover worker parsing, corrupted/duplicate output, 429 retention,
shared-deadline precedence and CLI wiring. No live provider or model was run to
validate this fix, and no outcome label changed.

## New source diagnostic, separate from old sealed probes

A fresh, frozen Danswer probe used only the original spreadsheet company/domain,
not outcomes or a modern alias. Its exact Common Crawl 2024-10 index request
returned one HTML 200 pointer dated 2024-02-27T19:40:51Z. The selected compressed
record would be 11,316 bytes. Its one exact range request did not complete before
the outer 45-second deadline (45.647 seconds including cleanup). Both HTTP
intents were saved; no complete body, admitted fact, model run, retry or alias
fallback resulted. The initial worker hash assertion failed before any child or
HTTP dispatch due to Windows newline translation; it was corrected to bind the
actual saved bytes before the protocol was dispatched. Failed history retained.

A subsequent bounded DNS-only check resolved both index and data hostnames in
under 0.1 seconds each. It made no HTTP request or connection and changed no
proxy, resolver or credentials. It does not identify whether TCP/TLS/headers/body
were responsible for the earlier failure and is not proof of HTTPS reachability.
The old Danswer attempt remains sealed; this fix is not permission to replay it.

## An alternative source lead remains held

Read-only GitHub exploration found a Danswer-associated issue with server-reported
created/updated dates before cutoff. That is not yet admitted historical evidence:
current repository visibility, renamed-repository binding and past public
availability were not independently established. Search filters alone are not a
verification, and current comments/labels/closed state cannot be silently added
to historical features. No new GitHub source provider or automatic fact was made.

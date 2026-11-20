# Metered historical research backend — November 19, 2026

Implemented by Yi-Nung with AI-assisted development, extending the existing
Rose Yu runtime and archive verifier. This is a bounded historical website
research backend, with offline integration checks. A newly executed real-company
model experiment and general web research are not claimed.

The existing runtime can now use
[`MeteredResearchProvider`](../../src/closed_loop/research_backend.py) in place of
`ArchivedWebsiteProvider` without changing the runtime provider contract:

```python
archive = ArchivedWebsiteProvider(request, gateway, budget, max_requests=6)
provider = MeteredResearchProvider(
    request, gateway, budget, backend, archive, max_navigation_steps=2
)
runtime = ClosedLoopRuntime(
    request, gateway, budget, lead, committee, provider
)
```

The injected model backend, lead, committee and archive transport share the
same `CallBudget`. A live backend must already have its separately authorized
API spend envelope; constructing this provider loads no credentials and creates
no live model client. The one-company smoke-test runner is the execution entry
point. This provider can also use deterministic injected test backends.

For each research task the provider first retrieves eligible archived website
content with the existing trusted archive verifier. It admits every returned
candidate through `TemporalGateway` **before** including that content in a
model prompt. The planner receives those admitted facts and up to 16 links
observed in their historical HTML. It can select one listed path or stop.
Each selected target gets its own CDX lookup and readable replay with matching
Memento timestamp. A dated link alone never establishes the target's content.
Newly admitted target pages can supply links for the next iteration.

The task's company, subject, question, domain anchor and decision cutoff remain
fixed. Arbitrary model-generated URLs, off-domain hints, post-cutoff hints and
hints without an admitted source are rejected. The planner cannot register
proofs, change identity, invoke a general search engine, read files, load Y or
read current company profiles. Source text is explicitly treated as untrusted
data. Model output selects navigation only and is never an admitted fact.

The default is at most two navigation model calls per research task, with an
explicit constructor limit of one to eight. Already visited paths cannot be
selected again during that task. The overall run's model-call, archive-HTTP,
concurrency and deadline caps still apply. Each fresh target needs room for two
HTTP reservations; otherwise the provider returns its already admitted evidence.
Model/provider, malformed-plan and metering errors stop the shared run budget
before returning previously admitted sources, preventing later model dispatch.
The runtime independently rechecks those candidates and records incomplete diligence as `MORE_DILIGENCE`, preserving unknowns.

Model accounting follows the existing backend seam: fixture planners consume
logical model reservations; an owning live backend performs its own physical
request and conservative dollar reservation once. Archive transport meters every
HTTP attempt separately, including index, replay and verified redirect handling.
`last_calls` contains planner invocation metadata, `trace` contains navigation and
stop events, and `receipts`/`attempts` expose the underlying archive verifier's
records. These counters are not an invoice and fixture calls are not paid calls.
No raw rejected source content is copied into the planner prompt or trace.

Verification:

```sh
python3 -m unittest discover -s tests -p 'test_research_backend.py' -v
```

The 15 synthetic offline tests cover iterative navigation, runtime compatibility,
unknown preservation, separate gateway/budget rejection, future and cross-company
source rejection, future/off-origin/unproven-link filtering, future target
rejection, invented/repeated path refusal, step and logical/physical HTTP/model
caps, terminal provider-error stops, and shared physical-model accounting without double counting. No external network or paid
model call is needed for these tests. They establish wiring and boundary checks,
not model research quality or historical prediction accuracy.

Limitations: search is confined to paths discoverable on justified company-domain
anchors, using the existing archive provider. Domain ownership at the historical
date remains a caller-supported identity assumption. General news and peer
discovery require new trusted historical adapters. Prompt injection can affect
navigation choices within the allowed set; source correctness, model reasoning
quality and pretrained future knowledge are not certified. This application-level
tool boundary does not replace an operating-system sandbox.

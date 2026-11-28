# Reviewed retrospective extraction rubric

Codex CLI drafted; Claude Code CLI ACCEPT, 2026-11-21. Root reviewed. This is a rubric, not an executed model-quality comparison.

## Acceptance rubric for the retrospective evidence-extraction demo

| Area | Acceptance criterion |
|---|---|
| Citation validity | Every factual claim cites a readable passage that supports the exact claim and identifies the correct company. Review each identity field separately. Flag unsupported claims, partial support, redirects, and unavailable bodies. An HTTP 200 or a URL slug alone is insufficient evidence. |
| Dated and mutable sources | Record the source date, version or capture date when available, and final URL. Admit a claim as pre-cutoff evidence only when a dated original or verified historical replay supports it. Label claims drawn from current mutable pages as retrospective observations. A record’s creation timestamp establishes record age only. |
| Unknown and abstention | Return `UNKNOWN` when admissible evidence is missing, ambiguous, or insufficient. Record the reason and distinguish unavailable sources from unattempted retrieval. Preserve `UNKNOWN` separately from verified negatives and exclude it from negative counts. |
| Fair baseline | Select the pilot from the identity-only cohort before reading outcomes. Give the simple prompted baseline and the guarded workflow identical admissible source material, extraction instructions, and budget. Freeze prompts, feature definitions, and split hashes before any outcome join. Apply the same review criteria to both and report results side by side. |
| Reporting and cost | Report source admission and rejection correctness, citation validity, unsupported claims, abstentions, retrieval availability, completion, and stop reasons. Give denominators for reported rates. Report model/API and HTTP usage, elapsed time, and actual cost against the approved ceiling for each arm. Keep coverage separate from extraction correctness. |

**Current status as of 2026-11-21.** Offline integration ran and demonstrated workflow control. The historical evidence gate remains open, the frozen comparison has yet to run, and the paid smoke run awaits historical gate clearance and fresh cost approval. The proposed smoke limits are one company, 24 API requests, six archive HTTP requests, eight minutes, and $0.20 reserved.

The cohort has 240 companies, with financing observed for 153, a composite observation for 164, 76 composite unknowns, and zero verified financing negatives. These are coverage counts. Acceptance applies only to retrospective evidence extraction. Training remains unauthorized, and the demo establishes no historical prediction or investment accuracy.
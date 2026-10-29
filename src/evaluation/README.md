# src/evaluation/ — not yet implemented

No evaluation code exists yet. This directory is a placeholder so the intended
structure is visible; it deliberately contains no stub implementations, because
a fake metric function is worse than an empty directory.

Planned, per
[`docs/research_log/2026-10-29_w24_backtest_design.md`](../../docs/research_log/2026-10-29_w24_backtest_design.md)
section 10:

- Top-K recommendation lists
- Precision@K
- outcome differences between `INVEST` and `PASS` groups
- DIALECTIC baseline vs. our Multi-Agent Investment Committee

Blocked on two things:

1. **`Y` is not finalised.** The raw outcome dimensions (survival/status,
   follow-on financing, acquisition, team growth, evidence quality) are
   deliberately kept separate and have not been aggregated into a label.
2. **The sponsor's investment mandate has not been received.** The mandate is a
   system input, so neither the baseline nor the comparison can be specified
   without it.

Portfolio/ranking metrics are preferred over company-level classification
accuracy: a VC does not make N independent binary calls, it builds a portfolio.

Any baseline comparison must state which DIALECTIC configuration was run. The
shipped defaults (3 pro / 3 contra, `k_best=[1,1]`, `max_iterations=2`) are not
the paper's configuration (K = 4).

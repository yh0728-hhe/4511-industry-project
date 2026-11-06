# results/verified/

Outputs that have been checked and can be cited elsewhere — in
`CURRENT_STATE.md`, in a research log, or to the sponsor.

A result belongs here only when all of the following are true:

1. the code that produced it is in `src/` and runs end to end;
2. the numbers have been checked against the inputs, not just eyeballed;
3. row counts, date filtering and entity matching have been verified;
4. its provenance is recorded — which commit, which source, which date;
5. nothing in it depends on a credential or a cache that is not reproducible.

Anything that fails one of these stays in `experiments/`.

Nothing is here yet. The first candidates are the 20-company end-to-end pilot
and an improved Funding Y.

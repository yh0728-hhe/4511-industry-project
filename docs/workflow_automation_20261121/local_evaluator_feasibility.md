# Optional local evaluator feasibility — 2026-11-26

Status: structural guard implemented and tested; NO detector installed, downloaded or executed. Default production workflow and Y unchanged. This is reuse investigation, not model training or a verified accuracy improvement.

## Primary-source inspection

LettuceDetect source revision: dcce161ff7c8a46147cae5f0bda14118bef7a2d6. [Transformer implementation](https://github.com/KRLabsOrg/LettuceDetect/blob/dcce161ff7c8a46147cae5f0bda14118bef7a2d6/lettucedetect/detectors/transformer.py), [package metadata](https://github.com/KRLabsOrg/LettuceDetect/blob/dcce161ff7c8a46147cae5f0bda14118bef7a2d6/pyproject.toml), [TinyLettuce documentation](https://github.com/KRLabsOrg/LettuceDetect/blob/dcce161ff7c8a46147cae5f0bda14118bef7a2d6/docs/TINYLETTUCE.md).

The upstream transformer path uses a pretrained token classifier. It can truncate long prompts; its multi-context chunk aggregation takes maximum unsupported probability across chunks. Neither behavior is silently adopted here. The token API returns token text, predicted class and probability, without answer character offsets. A correct tokenizer/offset bridge and a no-truncation preflight are still needed. The package entry point imports additional generation and RAG-fact-checker components; installing it is not equivalent to loading only the local transformer.

Candidate model identity from upstream docs: KRLabsOrg/tinylettuce-ettin-17m-en-v1. Its revision, weights, model-specific license, local Python3.13 compatibility, memory and latency have NOT been verified. Browser access to its model page failed. A separate bounded metadata request did not return and was interrupted; no weights were fetched. No alternate endpoint, credential or paid inference fallback was used.

## Implemented experiment-only contract

scripts/experiments/local_token_support_contract.py has no third-party imports or model/network calls. It validates an injected exact token count BEFORE inference, refuses overlength inputs, validates finite probabilities and Python character offsets, and requires coverage of every non-whitespace answer character. Empty or incomplete token output raises instead of returning a positive. A fixed0.5 threshold produces diagnostic flagged spans; overlapping or touching flagged ranges are merged with exact original substrings. Complete means structural coverage, not semantic truth or calibrated confidence. It is not a Ragas score and cannot replace historical source admission, claim review or recommendation gates.

Actual Claude implemented the module and8fake tests in58.746seconds, exit0 and is_error=false. Its restricted coding worker had no shell and correctly claimed no executed tests. Codex ran those tests, corrected the final-gate scope wording, added2boundary/invalid-input tests and included the imported experiment module in readiness fingerprints.42focused tests passed. Full readiness:1,065tests,1,062passed,3skipped; all6stages passed. These tests establish contract behavior, not detector quality.

## Next decision

Do not install or route production through this candidate until model artifacts and license are pinned, an isolated E-drive-only dependency plan is bounded, and tokenizer offsets plus no-truncation checks are verified. Any real comparison needs a separately frozen protocol. The incomplete18-call RAGTruth run remains sealed; this investigation does not retry its missing case or reset its allowance. External benchmarks may be pretrained and published scores are not our company's diligence accuracy.

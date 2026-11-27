"""Deterministic, pure-data follow-up case selection for a RAGTruth QA slice.

Source corpus: ParticleMedia/RAGTruth @ c103204b9ce28d6bbad859304bf30de72b8ed8fe
Raw files are consumed locally only; this script performs no network access,
no model calls, no agent calls, and performs no training. It reuses the
verification and selection helpers from ragtruth_reference_prepare_20261126.py
via importlib rather than editing that file. Selection happens before any new
model predictions exist, so it cannot be influenced by their outputs.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
from typing import Any

PRIOR_SCRIPT_NAME = "ragtruth_reference_prepare_20261126.py"

PREVIOUS_INPUTS_MAX_BYTES = 100_000
PREVIOUS_EXPECTED_COUNT = 6
PREVIOUS_EXPECTED_KEYS = {"case_id", "source_id", "question", "context", "response"}


def _load_prior_module():
    prior_path = Path(__file__).resolve().parent / PRIOR_SCRIPT_NAME
    spec = importlib.util.spec_from_file_location("ragtruth_reference_prepare_20261126", prior_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, prior_path


def _read_previous_inputs(path: Path) -> tuple[list[dict[str, Any]], bytes]:
    with path.open("rb") as stream:
        raw = stream.read(PREVIOUS_INPUTS_MAX_BYTES + 1)
    if len(raw) > PREVIOUS_INPUTS_MAX_BYTES:
        raise ValueError(f"{path}: exceeds max of {PREVIOUS_INPUTS_MAX_BYTES} bytes")

    records = json.loads(raw.decode("utf-8"))
    if not isinstance(records, list) or len(records) != PREVIOUS_EXPECTED_COUNT:
        raise ValueError(f"{path}: expected exactly {PREVIOUS_EXPECTED_COUNT} records")

    case_ids = set()
    source_ids = set()
    for rec in records:
        if not isinstance(rec, dict) or set(rec.keys()) != PREVIOUS_EXPECTED_KEYS:
            raise ValueError(f"{path}: record keys must be exactly {sorted(PREVIOUS_EXPECTED_KEYS)}")
        for key, value in rec.items():
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{path}: field {key} must be a nonblank string")
        case_ids.add(rec["case_id"])
        source_ids.add(rec["source_id"])

    if len(case_ids) != PREVIOUS_EXPECTED_COUNT or len(source_ids) != PREVIOUS_EXPECTED_COUNT:
        raise ValueError(f"{path}: case_id and source_id values must each be unique across {PREVIOUS_EXPECTED_COUNT} records")

    return records, raw


def select_followup(
    responses: list[dict[str, Any]],
    sources: Any,
    excluded_source_ids: set[Any],
    prior_module,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Pure selection: two sequential batches of 3+3 over 12 distinct sources."""
    filtered = [r for r in responses if r.get("source_id") not in excluded_source_ids]

    batch1_inputs, batch1_gold = prior_module.select_cases(filtered, sources)
    batch1_source_ids = {item["source_id"] for item in batch1_inputs}

    remaining = [r for r in filtered if r.get("source_id") not in batch1_source_ids]
    batch2_inputs, batch2_gold = prior_module.select_cases(remaining, sources)
    batch2_source_ids = {item["source_id"] for item in batch2_inputs}

    if batch1_source_ids & batch2_source_ids:
        raise ValueError("batch1 and batch2 source_ids must not overlap")

    return batch1_inputs, batch1_gold, batch2_inputs, batch2_gold


def main(argv=None) -> None:
    prior_module, prior_path = _load_prior_module()

    parser = argparse.ArgumentParser(
        description="Select a deterministic RAGTruth QA follow-up slice (12 new source-unique cases)."
    )
    parser.add_argument("--responses", required=True, type=Path)
    parser.add_argument("--sources", required=True, type=Path)
    parser.add_argument("--previous-inputs", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    if args.output_dir.exists():
        raise FileExistsError(f"output directory already exists: {args.output_dir}")

    responses, responses_raw = prior_module._read_verified_jsonl(
        args.responses, prior_module.RESPONSES_BLOB_SHA1,
        prior_module.RESPONSES_SIZE_BYTES, prior_module.RESPONSES_MAX_BYTES,
    )
    sources_records, sources_raw = prior_module._read_verified_jsonl(
        args.sources, prior_module.SOURCES_BLOB_SHA1,
        prior_module.SOURCES_SIZE_BYTES, prior_module.SOURCES_MAX_BYTES,
    )
    sources = {rec.get("source_id"): rec for rec in sources_records}

    previous_inputs, previous_raw = _read_previous_inputs(args.previous_inputs)
    previous_source_ids = {rec["source_id"] for rec in previous_inputs}

    b1_inputs, b1_gold, b2_inputs, b2_gold = select_followup(
        responses, sources, previous_source_ids, prior_module
    )

    model_inputs = b1_inputs + b2_inputs
    gold_records = b1_gold + b2_gold

    new_source_ids = {item["source_id"] for item in model_inputs}
    if new_source_ids & previous_source_ids:
        raise ValueError("follow-up source_ids must not overlap previously selected source_ids")
    if len(new_source_ids) != 12:
        raise ValueError(f"expected 12 unique source_ids, got {len(new_source_ids)}")

    case_ids = [item["case_id"] for item in model_inputs]

    inputs_bytes = prior_module._canonical_json_bytes(model_inputs)
    gold_bytes = prior_module._canonical_json_bytes(gold_records)

    args.output_dir.mkdir(parents=True)
    inputs_path = args.output_dir / "selected_inputs.json"
    gold_path = args.output_dir / "selected_gold.json"
    manifest_path = args.output_dir / "selection_manifest.json"

    inputs_path.write_bytes(inputs_bytes)
    gold_path.write_bytes(gold_bytes)

    prior_script_raw = prior_path.read_bytes()
    this_script_raw = Path(__file__).read_bytes()

    manifest = {
        "commit": prior_module.COMMIT,
        "responses_file": {
            "path": str(args.responses),
            "size_bytes": len(responses_raw),
            "sha256": hashlib.sha256(responses_raw).hexdigest(),
            "git_blob_sha1": prior_module.git_blob_sha1(responses_raw),
        },
        "sources_file": {
            "path": str(args.sources),
            "size_bytes": len(sources_raw),
            "sha256": hashlib.sha256(sources_raw).hexdigest(),
            "git_blob_sha1": prior_module.git_blob_sha1(sources_raw),
        },
        "previous_inputs_file": {
            "path": str(args.previous_inputs),
            "size_bytes": len(previous_raw),
            "sha256": hashlib.sha256(previous_raw).hexdigest(),
        },
        "preparer_scripts": {
            PRIOR_SCRIPT_NAME: {"sha256": hashlib.sha256(prior_script_raw).hexdigest()},
            Path(__file__).name: {"sha256": hashlib.sha256(this_script_raw).hexdigest()},
        },
        "output_files": {
            "selected_inputs.json": {"sha256": hashlib.sha256(inputs_bytes).hexdigest()},
            "selected_gold.json": {"sha256": hashlib.sha256(gold_bytes).hexdigest()},
        },
        "case_ids": case_ids,
        "batch_1_case_ids": [item["case_id"] for item in b1_inputs],
        "batch_2_case_ids": [item["case_id"] for item in b2_inputs],
        "unique_source_count": len(new_source_ids),
        "unique_source_ids": sorted(new_source_ids),
        "previously_excluded_source_ids": sorted(previous_source_ids),
        "selection_rule": (
            "exclude the 6 previously selected source_ids, then apply the prior "
            "script's select_cases() mechanical rule twice in original response "
            "order: once over the filtered stream for batch 1 (first 3 "
            "supported + 3 unsupported, 6 unique sources), then again over the "
            "remainder with batch 1's sources also excluded for batch 2 "
            "(another 3 + 3, 6 more unique sources); no resampling after "
            "viewing outputs; no model predictions are read or produced"
        ),
        "references_provenance": "human-annotated, publicly released RAGTruth dataset; pretraining exclusion is not established",
        "model_calls": 0,
        "http_requests": 0,
        "training": False,
        "Y_changed": False,
        "modifies_production": False,
        "raw_redistribution": False,
    }
    manifest_bytes = prior_module._canonical_json_bytes(manifest)
    manifest_path.write_bytes(manifest_bytes)

    print(f"selected {len(model_inputs)} follow-up cases across {len(new_source_ids)} unique sources")
    print(f"batch 1 case ids: {manifest['batch_1_case_ids']}")
    print(f"batch 2 case ids: {manifest['batch_2_case_ids']}")
    print(f"wrote: {inputs_path}, {gold_path}, {manifest_path}")


if __name__ == "__main__":
    main()

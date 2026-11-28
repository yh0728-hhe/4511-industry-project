"""Deterministic, pure-data case selection for a RAGTruth QA reproducibility slice.

Source corpus: ParticleMedia/RAGTruth @ c103204b9ce28d6bbad859304bf30de72b8ed8fe
Raw files are consumed locally only; this script performs no network access,
no model calls, and performs no training. Embedded web passages remain
subject to their original sources' rights and are not redistributed here.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

COMMIT = "c103204b9ce28d6bbad859304bf30de72b8ed8fe"

RESPONSES_BLOB_SHA1 = "f9ae5913fb9976684f3e13be3cd3465062db54cc"
RESPONSES_SIZE_BYTES = 21458735
RESPONSES_MAX_BYTES = 25 * 1024 * 1024

SOURCES_BLOB_SHA1 = "119277774009f110aa58596b93f9512f62594a89"
SOURCES_SIZE_BYTES = 15117971
SOURCES_MAX_BYTES = 16 * 1024 * 1024

QUESTION_MAX_BYTES = 1024
PASSAGES_MAX_BYTES = 6000
RESPONSE_MAX_BYTES = 1200

EXPECTED_CASE_IDS = [11904, 12012, 12018, 12044, 12219, 12233]

SELECTION_RULE = (
    "scan response.jsonl in original order; keep split=test, quality=good, "
    "task_type=QA records with nonblank question/passages/response within "
    "UTF-8 byte limits and a labels list; expected_supported is 1 iff labels "
    "is empty (authors' baseline treats implicit_true spans as unsupported); "
    "take the first 3 supported and first 3 unsupported cases whose "
    "source_id has not already been selected, stopping once both quotas of "
    "3 are filled"
)


def _utf8_len(s: str) -> int:
    return len(s.encode("utf-8"))


def git_blob_sha1(raw: bytes) -> str:
    header = b"blob " + str(len(raw)).encode("ascii") + b"\0"
    return hashlib.sha1(header + raw).hexdigest()


def select_cases(
    responses: list[dict[str, Any]], sources: Any
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Pure selection logic; exercised directly by synthetic unit tests."""
    if isinstance(sources, dict):
        source_map = dict(sources)
    else:
        source_map = {}
        for rec in sources:
            source_map[rec.get("source_id")] = rec

    selected: list[tuple[dict[str, Any], dict[str, Any]]] = []
    supported_count = 0
    unsupported_count = 0
    seen_source_ids: set[Any] = set()

    for r in responses:
        if supported_count >= 3 and unsupported_count >= 3:
            break

        if r.get("split") != "test":
            continue
        if r.get("quality") != "good":
            continue

        source_id = r.get("source_id")
        if not isinstance(source_id,str) or not source_id.strip():
            continue
        src = source_map.get(source_id)
        if not isinstance(src, dict):
            continue
        if src.get("task_type") != "QA":
            continue

        source_info = src.get("source_info")
        if not isinstance(source_info, dict):
            continue

        question = source_info.get("question")
        passages = source_info.get("passages")
        response_text = r.get("response")

        if not isinstance(question, str) or not question.strip():
            continue
        if not isinstance(passages, str) or not passages.strip():
            continue
        if not isinstance(response_text, str) or not response_text.strip():
            continue

        if _utf8_len(question) > QUESTION_MAX_BYTES:
            continue
        if _utf8_len(passages) > PASSAGES_MAX_BYTES:
            continue
        if _utf8_len(response_text) > RESPONSE_MAX_BYTES:
            continue

        labels = r.get("labels")
        if not isinstance(labels, list):
            continue

        if source_id in seen_source_ids:
            continue

        expected_supported = 1 if len(labels) == 0 else 0

        if expected_supported == 1 and supported_count >= 3:
            continue
        if expected_supported == 0 and unsupported_count >= 3:
            continue

        implicit_true_span_count = sum(
            1
            for label in labels
            if isinstance(label, dict) and label.get("implicit_true") is True
        )

        case_id = "ragtruth-response-" + str(r.get("id"))

        model_input = {
            "case_id": case_id,
            "source_id": source_id,
            "question": question,
            "context": passages,
            "response": response_text,
        }
        gold = {
            "case_id": case_id,
            "expected_supported": expected_supported,
            "original_span_count": len(labels),
            "implicit_true_span_count": implicit_true_span_count,
        }

        seen_source_ids.add(source_id)
        if expected_supported == 1:
            supported_count += 1
        else:
            unsupported_count += 1
        selected.append((model_input, gold))

    if supported_count < 3 or unsupported_count < 3:
        raise ValueError(
            "insufficient cases: found "
            f"{supported_count} supported and {unsupported_count} unsupported "
            "with globally unique source_id (need 3 of each)"
        )

    model_inputs = [pair[0] for pair in selected]
    gold_records = [pair[1] for pair in selected]
    return model_inputs, gold_records


def _read_verified_jsonl(
    path: Path, expected_sha1: str, expected_size: int, max_bytes: int
) -> tuple[list[dict[str, Any]], bytes]:
    with path.open("rb") as stream:
        raw = stream.read(max_bytes+1)

    if len(raw) > max_bytes:
        raise ValueError(f"{path}: {len(raw)} bytes exceeds max of {max_bytes} bytes")
    if len(raw) != expected_size:
        raise ValueError(f"{path}: size {len(raw)} does not match pinned size {expected_size}")

    actual_sha1 = git_blob_sha1(raw)
    if actual_sha1 != expected_sha1:
        raise ValueError(
            f"{path}: git blob sha1 {actual_sha1} does not match pinned {expected_sha1}"
        )

    text = raw.decode("utf-8")
    records = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(json.loads(line))
    return records, raw


def _canonical_json_bytes(data: Any) -> bytes:
    text = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=False)
    return text.encode("utf-8")+b"\n"


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(
        description="Select a deterministic RAGTruth QA reproducibility slice."
    )
    parser.add_argument("--responses", required=True, type=Path)
    parser.add_argument("--sources", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args(argv)

    if args.output_dir.exists():
        raise FileExistsError(f"output directory already exists: {args.output_dir}")

    responses, responses_raw = _read_verified_jsonl(
        args.responses, RESPONSES_BLOB_SHA1, RESPONSES_SIZE_BYTES, RESPONSES_MAX_BYTES
    )
    sources_records, sources_raw = _read_verified_jsonl(
        args.sources, SOURCES_BLOB_SHA1, SOURCES_SIZE_BYTES, SOURCES_MAX_BYTES
    )
    sources = {rec.get("source_id"): rec for rec in sources_records}

    model_inputs, gold_records = select_cases(responses, sources)

    case_ids = [item["case_id"] for item in model_inputs]
    numeric_ids = [int(cid.rsplit("-", 1)[-1]) for cid in case_ids]
    if numeric_ids != EXPECTED_CASE_IDS:
        raise ValueError(
            f"selected case ids {numeric_ids} do not match expected pinned ids {EXPECTED_CASE_IDS}"
        )

    unique_source_ids = sorted({item["source_id"] for item in model_inputs})

    inputs_bytes = _canonical_json_bytes(model_inputs)
    gold_bytes = _canonical_json_bytes(gold_records)

    args.output_dir.mkdir(parents=True)
    inputs_path = args.output_dir / "selected_inputs.json"
    gold_path = args.output_dir / "selected_gold.json"
    manifest_path = args.output_dir / "selection_manifest.json"

    inputs_path.write_bytes(inputs_bytes)
    gold_path.write_bytes(gold_bytes)

    manifest = {
        "commit": COMMIT,
        "responses_file": {
            "path": str(args.responses),
            "size_bytes": len(responses_raw),
            "sha256": hashlib.sha256(responses_raw).hexdigest(),
            "git_blob_sha1": git_blob_sha1(responses_raw),
        },
        "sources_file": {
            "path": str(args.sources),
            "size_bytes": len(sources_raw),
            "sha256": hashlib.sha256(sources_raw).hexdigest(),
            "git_blob_sha1": git_blob_sha1(sources_raw),
        },
        "output_files": {
            "selected_inputs.json": {"sha256": hashlib.sha256(inputs_bytes).hexdigest()},
            "selected_gold.json": {"sha256": hashlib.sha256(gold_bytes).hexdigest()},
        },
        "case_ids": case_ids,
        "unique_source_count": len(unique_source_ids),
        "unique_source_ids": unique_source_ids,
        "selection_rule": SELECTION_RULE,
        "model_calls": 0,
        "redistribution": False,
        "training": False,
    }
    manifest_bytes = _canonical_json_bytes(manifest)
    manifest_path.write_bytes(manifest_bytes)

    print(f"selected {len(model_inputs)} cases across {len(unique_source_ids)} unique sources")
    print(f"case ids: {case_ids}")
    print(f"wrote: {inputs_path}, {gold_path}, {manifest_path}")


if __name__ == "__main__":
    main()

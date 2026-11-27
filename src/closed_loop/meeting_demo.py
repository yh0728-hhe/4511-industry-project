"""Offline, one-command regeneration of the 2026-11-11 meeting demo artifacts.

Reads only committed JSON result files already in the repository (the sealed
Abel API pilot trace, the fixture/native-graph comparison, and the pilot_20
local-seed observation report). Makes no network or model calls. Writes
results/candidates/meeting_demo_20261111/{results.csv,manifest.json}.

Run from repository root: python -m closed_loop.meeting_demo
"""
import csv
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "results" / "candidates" / "meeting_demo_20261111"

SOURCES = {
    "abel_pilot_closeout": ROOT / "results/candidates/closed_loop_offline/approved_api_pilot_closeout.json",
    "abel_live_result": ROOT / "results/candidates/closed_loop_offline/live_one_company_result.json",
    "native_graph_comparison": ROOT / "results/candidates/closed_loop_offline/native_graph_comparison.json",
    "fixture_runs": ROOT / "results/candidates/closed_loop_offline/fixture_runs.json",
    "pilot_20_local_seed": ROOT / "experiments/pilot_20/pilot_20_local_seed_run_report.json",
}

ABEL_CUTOFF_UTC = "2024-04-04T23:59:59+00:00"


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(key: str):
    path = SOURCES[key]
    return json.loads(path.read_text(encoding="utf-8")), sha256_of(path), path


def relpath(path: Path) -> str:
    return str(path.relative_to(ROOT)).replace("\\", "/")


def build_rows():
    rows = []

    closeout, closeout_hash, closeout_path = load("abel_pilot_closeout")
    rows.append({
        "company": "Abel",
        "run_id": "abel_api_pilot_budget_closeout",
        "mode": "real_api_pilot_budget_record",
        "cached_vs_new": "cached_historical_run_not_rerun_today",
        "date_guard": f"cutoff_{ABEL_CUTOFF_UTC}",
        "result": closeout["status"],
        "status_of_y": "N/A_NOT_Y_FUNDING_DATASET",
        "source_artifact_path": relpath(closeout_path),
        "source_artifact_sha256": closeout_hash,
    })

    live, live_hash, live_path = load("abel_live_result")
    rows.append({
        "company": live["company_name"],
        "run_id": f"abel_live_smoke_{live['started_utc']}",
        "mode": "real_api_pilot_guarded_smoke",
        "cached_vs_new": "cached_historical_run_not_rerun_today",
        "date_guard": f"cutoff_{ABEL_CUTOFF_UTC}_archive_memento_{live['archive_receipts'][0]['memento_datetime']}",
        "result": live["decision"],
        "status_of_y": "N/A_NOT_Y_FUNDING_DATASET",
        "source_artifact_path": relpath(live_path),
        "source_artifact_sha256": live_hash,
    })

    native, native_hash, native_path = load("native_graph_comparison")
    for case_name, case in native["cases"].items():
        rows.append({
            "company": f"SYNTHETIC_FIXTURE_{case_name.upper()}",
            "run_id": f"native_graph_comparison_{case_name}",
            "mode": "offline_fixture_dependency_injected",
            "cached_vs_new": "cached_fixture_not_a_real_company",
            "date_guard": "not_applicable_fixture_has_no_cutoff",
            "result": case["result"]["decision"],
            "status_of_y": "N/A_FIXTURE_NOT_REAL_COMPANY",
            "source_artifact_path": relpath(native_path),
            "source_artifact_sha256": native_hash,
        })

    fixtures, fixtures_hash, fixtures_path = load("fixture_runs")
    for case_name, case in fixtures.items():
        rows.append({
            "company": f"SYNTHETIC_FIXTURE_{case_name.upper()}",
            "run_id": f"run_fixtures_{case_name}",
            "mode": "offline_fixture",
            "cached_vs_new": "cached_fixture_not_a_real_company",
            "date_guard": "not_applicable_fixture_has_no_cutoff",
            "result": case["decision"],
            "status_of_y": "N/A_FIXTURE_NOT_REAL_COMPANY",
            "source_artifact_path": relpath(fixtures_path),
            "source_artifact_sha256": fixtures_hash,
        })

    pilot20, pilot20_hash, pilot20_path = load("pilot_20_local_seed")
    rows.append({
        "company": "pilot_20_local_seed_batch(20_companies,all_pending)",
        "run_id": "pilot_20_local_seed_observation",
        "mode": "offline_spreadsheet_observation_no_evidence_collected",
        "cached_vs_new": "cached_historical_run_not_rerun_today",
        "date_guard": "all_null_evidence_dates_all_pending",
        "result": pilot20["overall"],
        "status_of_y": "N/A_NOT_Y_FUNDING_DATASET_SPREADSHEET_OBSERVATION_ONLY",
        "source_artifact_path": relpath(pilot20_path),
        "source_artifact_sha256": pilot20_hash,
    })

    return rows


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = build_rows()

    csv_path = OUT_DIR / "results.csv"
    fieldnames = ["company", "run_id", "mode", "cached_vs_new", "date_guard",
                  "result", "status_of_y", "source_artifact_path", "source_artifact_sha256"]
    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    manifest = {
        "generated_by": "src/closed_loop/meeting_demo.py",
        "note": "Offline aggregation of committed artifacts; no model/network calls made during generation.",
        "real_company_rows": sum(1 for r in rows if r["mode"].startswith("real_")),
        "fixture_rows": sum(1 for r in rows if "fixture" in r["mode"] and not r["mode"].startswith("real_")),
        "other_rows": sum(1 for r in rows if "fixture" not in r["mode"] and not r["mode"].startswith("real_")),
        "source_artifacts": {
            key: {"path": relpath(path), "sha256": sha256_of(path)}
            for key, path in SOURCES.items()
        },
        "deterministic": True,
        "results_csv": relpath(csv_path),
        "results_csv_sha256": None,
    }
    manifest["results_csv_sha256"] = sha256_of(csv_path)

    manifest_path = OUT_DIR / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")

    print(f"wrote {relpath(csv_path)} ({len(rows)} rows)")
    print(f"wrote {relpath(manifest_path)}")


if __name__ == "__main__":
    main()

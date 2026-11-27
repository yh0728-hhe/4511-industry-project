"""Reproducible offline readiness run with checkpoints; never dispatches paid calls."""
from contextlib import contextmanager
from datetime import datetime, timezone
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
VERSION = 'workflow-readiness-v1'
OUT = ROOT / 'results/scratch/workflow_20261121'


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(path, value):
    """Atomic replace keeps an interrupted write from corrupting the last checkpoint."""
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    os.replace(temp, path)


def plan(root=ROOT):
    # Code/config and validation labels are fingerprinted, NOT provided to a model.
    paths = list((root / 'src').rglob('*.py'))
    paths += list((root / 'tests').glob('test_*.py'))
    paths += [root / name for name in (
        'scripts/experiments/prepare_company_review.py',
        'scripts/experiments/ragtruth_reference_prepare_20261126.py',
        'scripts/experiments/ragtruth_reference_predict_20261126.py',
        'scripts/experiments/ragtruth_reference_grade_20261126.py',
        'scripts/experiments/local_token_support_contract.py',
        'scripts/experiments/whole_response_reference_predict_20261126.py',
        'scripts/experiments/ragtruth_followup_prepare_20261126.py',
        'scripts/experiments/ragtruth_followup_predict_20261126.py',
        'scripts/experiments/ragtruth_followup_grade_20261126.py',
        'experiments/closed_loop_offline/weekly_smoke.py',
        'experiments/closed_loop_offline/run_fixtures.py',
        'data/processed/w24_spreadsheet_2024-03-25.csv',
        'data/team_snapshot_20261118/composite_y.csv',
        'data/team_snapshot_20261118/manifest.json',
        'data/team_snapshot_20261118/validate_snapshot.py',
        'results/candidates/funding_y_source_grace_v1/company_labels.csv',
        'results/candidates/outcome_coverage_v1/company_outcome_coverage.csv')]
    fingerprints = {str(p.relative_to(root)).replace('\\', '/'):
                    hashlib.sha256(p.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
                    for p in sorted(set(paths))}
    value = dict(version=VERSION, mode='OFFLINE_ONLY', source_sha256=fingerprints,
                 model_api_calls_allowed=0, external_archive_requests_allowed=0,
                 training_allowed=False, live_smoke_allowed=False,
                 outcome_files_role='Validation/evaluation audit only; never model feature inputs.')
    value['fingerprint'] = digest(value)
    return value


def training_assessment(root=ROOT):
    def read(name):
        with (root / name).open(encoding='utf-8-sig', newline='') as stream:
            return list(csv.DictReader(stream))
    funding = read('results/candidates/funding_y_source_grace_v1/company_labels.csv')
    outcomes = read('results/candidates/outcome_coverage_v1/company_outcome_coverage.csv')
    if len(funding) != 240 or len({r['company_id'] for r in funding}) != 240:
        raise ValueError('Expected the unique 240-company cohort')
    if {r['company_id'] for r in funding} != {r['company_id'] for r in outcomes}:
        raise ValueError('Outcome and financing cohorts differ')
    # Coverage is a missingness/ascertainment flag, not supervised investment success.
    negative = sum(r['negative_label_approved'] == 'YES' for r in funding)
    return dict(cohort=len(funding), financing_observed=sum(r['funding_y'] == 'YES' for r in funding),
                composite_observed=sum(r['outcome_covered'] == 'YES' for r in outcomes),
                verified_financing_negatives=negative, supervised_training_ready=False,
                rule='UNKNOWN is not zero; evidence coverage is not investment success.',
                blockers=['Success target and source-specific windows need team/sponsor agreement.',
                          'No approved two-class outcome dataset or historical feature manifest.',
                          'No frozen holdout or leakage-reviewed evaluation protocol.',
                          'No independently adjudicated company-quality reference set or matched-budget quality result.'],
                next_step='Validate the retrieval/decision baseline before considering training.')


@contextmanager
def lease(directory):
    lock = directory / '.run.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    try:
        os.write(fd, json.dumps({'pid': os.getpid(), 'started_utc': datetime.now(timezone.utc).isoformat()}).encode())
        os.close(fd)
        fd = None
        yield
    finally:
        if fd is not None:
            os.close(fd)
        lock.unlink(missing_ok=True)


def steps(root, directory):
    py = [sys.executable, '-X', 'utf8']
    return [
        ('runtime_tests', py + ['-W', 'ignore::ResourceWarning', '-m', 'unittest', 'discover', '-s', 'tests', '-p', 'test_*.py', '-q'], []),
        ('funding_tests', py + ['-W', 'ignore::ResourceWarning', '-m', 'unittest', 'discover', '-s', 'src/funding/tests', '-p', 'test_*.py', '-q'], []),
        ('outcome_tests', py + ['-m', 'unittest', 'discover', '-s', 'src/outcome_tracking', '-p', 'test_*.py', '-q'], []),
        ('snapshot_validation', py + ['data/team_snapshot_20261118/validate_snapshot.py'], []),
        ('synthetic_loop', py + ['experiments/closed_loop_offline/run_fixtures.py', str(directory / 'fixtures.json')], ['fixtures.json']),
        ('adagy_preflight', py + ['experiments/closed_loop_offline/weekly_smoke.py', '--plan-output', str(directory / 'adagy_plan.json')], ['adagy_plan.json'])]


def execute(command, root, timeout):
    env = os.environ.copy()
    env['PYTHONPATH'] = str(root / 'src')
    env['PYTHONUTF8'] = '1'
    result = subprocess.run(command, cwd=root, env=env, capture_output=True, timeout=timeout)
    return result.returncode, (result.stdout + result.stderr)[-131072:]


def run(run_id, *, root=ROOT, output=OUT, resume=False, max_seconds=180, executor=execute, catalog=None):
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,63}', run_id):
        raise ValueError('Bounded run_id with letters, digits, dash or underscore required')
    if type(max_seconds) is not int or not 1 <= max_seconds <= 1800:
        raise ValueError('Workflow deadline must be 1..1800 seconds')
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    directory = (output / run_id).resolve()
    directory.relative_to(output)
    directory.mkdir(exist_ok=True)
    state_path = directory / 'receipt.json'
    with lease(directory):
        current = plan(root)
        if state_path.exists():
            if not resume:
                raise ValueError('Run exists: choose --resume or a new run_id; previous result preserved')
            state = json.loads(state_path.read_text(encoding='utf-8'))
            if state.get('run_id') != run_id or state.get('mode') != 'OFFLINE_ONLY':
                raise ValueError('Receipt identity/mode mismatch: resume refused')
            if file_hash(directory / 'plan.json') != state['plan_snapshot_sha256']:
                raise ValueError('Saved plan changed: resume refused')
            if state['plan_fingerprint'] != current['fingerprint']:
                raise ValueError('Source inputs changed: resume refused, choose a new run_id')
            for record in state['steps'].values():
                if record['status'] == 'PASSED':
                    for name, expected in record['sha256'].items():
                        artifact = (directory / name).resolve()
                        artifact.relative_to(directory)
                        if not artifact.is_file() or file_hash(artifact) != expected:
                            raise ValueError('Completed-step artifact changed: resume refused')
        else:
            if resume:
                raise ValueError('Cannot resume a missing receipt')
            state = dict(run_id=run_id, plan_fingerprint=current['fingerprint'], steps={},
                         status='RUNNING', mode='OFFLINE_ONLY', paid_api_calls=0,
                         external_network_calls_dispatched_by_orchestrator=0,
                         training_run=False, network_scope='Fixed offline commands; Python guard in regression fixtures, not an OS sandbox.')
            save(directory / 'plan.json', current)
            state['plan_snapshot_sha256'] = file_hash(directory / 'plan.json')
            save(state_path, state)
        deadline = time.monotonic() + max_seconds
        for name, command, artifacts in (catalog if catalog is not None else steps(root, directory)):
            if state['steps'].get(name, {}).get('status') == 'PASSED':
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                state['status'] = 'STOPPED_DEADLINE'
                save(state_path, state)
                return state
            state['steps'][name] = dict(status='RUNNING')
            state['status'] = 'RUNNING'
            save(state_path, state)
            started = time.monotonic()
            try:
                code, log = executor(command, root, remaining)
                (directory / (name + '.log')).write_bytes(log)
                names = [name + '.log'] + (artifacts if code == 0 else [])
                hashes = {item: file_hash(directory / item) for item in names}
                state['steps'][name] = dict(status='PASSED' if code == 0 else 'FAILED', exit_code=code,
                                          elapsed_seconds=round(time.monotonic() - started, 3), sha256=hashes)
                if code != 0:
                    state['status'] = 'STOPPED_STEP_FAILED'
                    save(state_path, state)
                    return state
            except subprocess.TimeoutExpired:
                state['steps'][name] = dict(status='TIMED_OUT', sha256={})
                state['status'] = 'STOPPED_DEADLINE'
                save(state_path, state)
                return state
            except Exception as exc:
                state['steps'][name] = dict(status='FAILED', error_type=type(exc).__name__, sha256={})
                state['status'] = 'STOPPED_STAGE_ERROR'
                save(state_path, state)
                return state
            save(state_path, state)
        try:
            state['training_assessment'] = training_assessment(root)
        except Exception as exc:
            state.update(status='STOPPED_ASSESSMENT_ERROR', error_type=type(exc).__name__)
            save(state_path, state)
            return state
        state['status'] = 'OFFLINE_CHECKS_PASSED_LIVE_AND_TRAINING_NOT_RUN'
        save(state_path, state)
        return state


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-id', required=True)
    parser.add_argument('--resume', action='store_true')
    parser.add_argument('--max-seconds', type=int, default=180)
    args = parser.parse_args(argv)
    try:
        result = run(args.run_id, resume=args.resume, max_seconds=args.max_seconds)
    except FileExistsError:
        print(json.dumps(dict(status='REFUSED_RUN_LOCK_HELD', next_step='Inspect the recorded owner before manually recovering a stale lock; no automatic deletion.')))
        return 2
    except ValueError as exc:
        print(json.dumps(dict(status='REFUSED_INVALID_OR_CHANGED_RUN', reason=str(exc))))
        return 2
    summary = {key: result[key] for key in ('run_id', 'status', 'paid_api_calls', 'training_run')}
    summary['step_statuses'] = {name: record['status'] for name, record in result['steps'].items()}
    print(json.dumps(summary, indent=2))
    if result['status'] != 'OFFLINE_CHECKS_PASSED_LIVE_AND_TRAINING_NOT_RUN':
        # Fixed offline test logs only; never raw provider/credential error text.
        for name, record in result['steps'].items():
            log = OUT / args.run_id / (name + '.log')
            if record['status'] != 'PASSED' and log.is_file():
                print(log.read_text(encoding='utf-8', errors='replace')[-6000:], file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    sys.exit(main())

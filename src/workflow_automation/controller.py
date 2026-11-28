"""Finite CLI handoff rehearsal. No scheduler, quota polling, retries or research API."""
from datetime import datetime, timezone
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import signal
import subprocess
import sys
import time

from .readiness import ROOT, digest, file_hash, lease, save

VERSION = 'bounded-handoff-v1'
TERMINAL = {'DONE', 'BLOCKED', 'STOPPED', 'WAITING_QUOTA'}
TASK = 'draft-and-review-evidence-rubric-v1'
SCHEMA = {'type': 'object', 'properties': {
    'verdict': {'type': 'string', 'enum': ['ACCEPT', 'REVISE']},
    'summary': {'type': 'string'}, 'findings': {'type': 'array', 'items': {'type': 'string'}}},
    'required': ['verdict', 'summary', 'findings'], 'additionalProperties': False}


def stamp():
    return datetime.now(timezone.utc).isoformat()


def source_identity(root):
    paths = sorted(set(list((root/'src/workflow_automation').glob('*.py')) +
                       [root/'docs/workflow_automation_20261121/evaluation_gate.json',
                        root/'data/metadata/workflow_20261121/historical_gate_codex_review.json']))
    return {str(p.relative_to(root)).replace('\\', '/'): file_hash(p) for p in paths}


def validate_review(text):
    value = json.loads(text)
    if not isinstance(value, dict) or set(value) != {'verdict', 'summary', 'findings'}:
        raise ValueError('Malformed review keys')
    if value['verdict'] not in ('ACCEPT', 'REVISE') or not isinstance(value['summary'], str) or not value['summary'].strip():
        raise ValueError('Malformed review verdict/summary')
    if not isinstance(value['findings'], list) or not all(isinstance(x, str) for x in value['findings']):
        raise ValueError('Malformed findings')
    if value['verdict'] == 'ACCEPT' and value['findings']:
        raise ValueError('ACCEPT cannot contain unresolved findings')
    return value


def execute_process(command, cwd, timeout):
    """Timeout terminates the owned process tree; never leave model grandchildren running."""
    options = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
    proc = subprocess.Popen(command, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, **options)
    try:
        out, err = proc.communicate(timeout=timeout)
        return proc.returncode, out, err
    except subprocess.TimeoutExpired:
        if os.name == 'nt':
            subprocess.run(['taskkill', '/PID', str(proc.pid), '/T', '/F'], capture_output=True, timeout=15)
        else:
            os.killpg(proc.pid, signal.SIGKILL)
        out, err = proc.communicate(timeout=15)
        return 124, out, err


def quota_error(message):
    # Called on provider error envelopes ONLY, never successful task text/documents.
    return bool(re.search(r'usage limit|rate.?limit|quota|out of usage|hit your limit|429', message, re.I))


def cli_worker(role, root, directory, draft, timeout):
    constraints = ('No commands, network, tools, delegation, file changes, paid research, or training. '
                   'Only produce the requested output. UNKNOWN is not zero; coverage is not accuracy. ')
    context = (root/'docs/workflow_automation_20261121/evaluation_gate.json').read_text(encoding='utf-8')
    context += (root/'data/metadata/workflow_20261121/historical_gate_codex_review.json').read_text(encoding='utf-8')
    if role == 'codex':
        executable = shutil.which('codex')
        prompt = (constraints + 'Draft a concise acceptance rubric for a RETROSPECTIVE evidence-extraction demo, '
                  'not a historical prediction experiment. Include citation validity, dated-vs-mutable sources, '
                  'unknown/abstention, fair equal-input baseline and cost reporting. No invented metrics. '
                  'Write plain markdown, no fenced code. Supplied approved context:\n' + context)
        output = directory/'codex-last-message.md'
        command = [executable or 'codex', 'exec', '--sandbox', 'read-only', '--ephemeral', '--json',
                   '--ignore-user-config', '--skip-git-repo-check', '-c', 'approval_policy="never"', '-o', str(output), prompt]
    else:
        executable = shutil.which('claude')
        prompt = (constraints + 'Review this draft against the approved context. Return ONLY JSON with '
                  'verdict ACCEPT or REVISE, nonempty summary, findings array of unresolved issues. '
                  'ACCEPT requires empty findings. Do not use markdown fences. Context:\n' + context + '\nDRAFT:\n' + draft)
        command = [executable or 'claude', '--safe-mode', '--permission-mode', 'dontAsk', '--tools', '',
                   '--disable-slash-commands', '--no-session-persistence', '--output-format', 'json',
                   '--json-schema', json.dumps(SCHEMA), '-p', prompt]
    if not executable:
        return {'status': 'BLOCKED', 'reason': 'CLI_NOT_FOUND', 'text': ''}
    code, out, err = execute_process(command, directory, timeout)
    (directory/(role+'-stdout.log')).write_bytes(out)
    (directory/(role+'-stderr.log')).write_bytes(err)
    events = []
    if role == 'codex':
        for line in out.decode('utf-8', errors='replace').splitlines():
            try: events.append(json.loads(line))
            except ValueError: pass
        errors = [str(e.get('message', e.get('error', ''))) for e in events if e.get('type') in ('error', 'turn.failed')]
        text = output.read_text(encoding='utf-8') if output.exists() else ''
    else:
        try:
            envelope = json.loads(out)
            errors = [str(envelope.get('result', ''))] if envelope.get('is_error') else []
            result = envelope.get('structured_output', envelope.get('result', ''))
            text = json.dumps(result) if isinstance(result, dict) else result
        except ValueError:
            errors, text = ['Malformed Claude envelope'], ''
    if code == 124:
        return {'status': 'BLOCKED', 'reason': 'TIMEOUT', 'text': ''}
    if errors:
        return {'status': 'WAITING_QUOTA' if any(quota_error(e) for e in errors) else 'BLOCKED',
                'reason': 'PROVIDER_ERROR', 'text': ''}
    if code or not text.strip():
        return {'status': 'BLOCKED', 'reason': 'CLI_FAILED_OR_EMPTY', 'text': ''}
    return {'status': 'OK', 'text': text}


def run(run_id, *, root=ROOT, output=None, live=False, resume=False, worker=cli_worker,
        now=time.time, stop_file=None):
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', run_id):
        raise ValueError('Unsafe run id')
    directory = (Path(output) if output else root/'results/scratch/workflow_20261121/handoff')/run_id
    directory.mkdir(parents=True, exist_ok=True)
    stop_file = Path(stop_file) if stop_file else root/'coordination/STOP'
    config = {'version': VERSION, 'task': TASK, 'mode': 'LIVE_CLI' if live else 'DRY_RUN',
              'max_model_invocations': 2, 'max_seconds': 1200, 'sources': source_identity(root)}
    with lease(directory):
        receipt = directory/'receipt.json'
        if receipt.exists():
            if not resume:
                raise ValueError('Run exists; use resume')
            state = json.loads(receipt.read_text(encoding='utf-8'))
            if state['run_id'] != run_id or state['config_hash'] != digest(config):
                raise ValueError('Run identity/config/source mismatch')
            if (digest(state['config']) != state['config_hash'] or
                    type(state['attempts']) is not int or not 0 <= state['attempts'] <= 2 or
                    len(state['events']) != state['attempts'] or
                    [e['attempt'] for e in state['events']] != list(range(1, state['attempts']+1)) or
                    [e['role'] for e in state['events']] != ['codex', 'claude'][:state['attempts']]):
                raise ValueError('Inconsistent persisted budget/events')
            if state['status'] not in TERMINAL | {'READY', 'RUNNING', 'REVIEW', 'REVIEW_RUNNING'}:
                raise ValueError('Unknown persisted state')
            for a in state['artifacts'].values():
                if file_hash(directory/a['path']) != a['sha256']:
                    raise ValueError('Saved artifact tampered/missing')
            if state['status'] in ('RUNNING', 'REVIEW_RUNNING'):
                state.update(status='BLOCKED', reason='AMBIGUOUS_PREVIOUS_DISPATCH_NO_RETRY')
                save(receipt, state)
            if state['status'] in TERMINAL:
                return state
        else:
            state = {'run_id': run_id, 'config': config, 'config_hash': digest(config),
                     'status': 'READY', 'created_utc': stamp(), 'deadline_epoch': now()+1200,
                     'attempts': 0, 'artifacts': {}, 'events': [], 'paid_research_api_calls': 0,
                     'training_run': False, 'writeback_verified': False}
            save(receipt, state)
        if not live:
            return state
        for role, active, next_state in [('codex', 'RUNNING', 'REVIEW'), ('claude', 'REVIEW_RUNNING', 'DONE')]:
            if role in state['artifacts']:
                continue
            if source_identity(root) != config['sources']:
                state.update(status='BLOCKED', reason='SOURCE_CHANGED_DURING_RUN')
                save(receipt, state); return state
            if stop_file.exists() or now() >= state['deadline_epoch'] or state['attempts'] >= 2:
                state.update(status='STOPPED', reason='STOP_DEADLINE_OR_GLOBAL_CEILING')
                save(receipt, state); return state
            # Intent and cumulative invocation count are durable BEFORE launching any worker.
            state.update(status=active, attempts=state['attempts']+1)
            state['events'].append({'role': role, 'attempt': state['attempts'], 'intent_utc': stamp()})
            save(receipt, state)
            draft = (directory/'codex.md').read_text(encoding='utf-8') if role == 'claude' else ''
            try:
                result = worker(role, root, directory, draft, min(480, state['deadline_epoch']-now()))
            except Exception as error:
                state.update(status='BLOCKED', reason='WORKER_EXCEPTION_'+type(error).__name__)
                save(receipt, state); return state
            if result.get('status') != 'OK':
                state.update(status='WAITING_QUOTA' if result.get('status') == 'WAITING_QUOTA' else 'BLOCKED',
                             reason=result.get('reason', 'WORKER_FAILURE'))
                save(receipt, state); return state
            text = result.get('text', '')
            try:
                if not isinstance(text, str) or not text.strip():
                    raise ValueError('Empty worker result')
                if role == 'claude':
                    verdict = validate_review(text)
                    if verdict['verdict'] == 'REVISE':
                        next_state = 'BLOCKED'
                        state['reason'] = 'REVIEW_REQUESTED_CHANGES_NO_AUTOMATIC_LOOP'
            except (ValueError, TypeError):
                state.update(status='BLOCKED', reason='MALFORMED_WORKER_RESULT')
                save(receipt, state); return state
            artifact = directory/(role+'.md' if role == 'codex' else role+'.json')
            artifact.write_text(text, encoding='utf-8')
            state['artifacts'][role] = {'path': artifact.name, 'sha256': file_hash(artifact)}
            state.update(status=next_state)
            save(receipt, state)
            if next_state == 'BLOCKED': return state
        return state


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--run-id', required=True)
    p.add_argument('--live-rehearsal', action='store_true')
    p.add_argument('--resume', action='store_true')
    args = p.parse_args()
    try:
        result = run(args.run_id, live=args.live_rehearsal, resume=args.resume)
        print(json.dumps({'run_id': result['run_id'], 'status': result['status'], 'attempts': result['attempts'],
                          'writeback_verified': result['writeback_verified']}))
        return 0 if result['status'] in ('READY', 'DONE') else 2
    except (ValueError, OSError) as error:
        print(json.dumps({'status': 'REFUSED', 'reason': str(error)})); return 2


if __name__ == '__main__':
    sys.exit(main())

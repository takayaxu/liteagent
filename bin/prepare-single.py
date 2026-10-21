#!/usr/bin/env python3
"""Prepare one immutable task snapshot from active source, without starting it."""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent.parent
KIT = ROOT / 'src/adapter_versions/v2_expanded/docs/v3-repair-20261017/prepare_single.py'


def dump(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--order', type=int, required=True)
    parser.add_argument('--owner', default='v3-thinking-repair')
    parser.add_argument('--profile', type=Path, default=ROOT / 'configs/single-task-v3-thinking.json')
    args = parser.parse_args()
    spec = importlib.util.spec_from_file_location('repair_version', ROOT / 'bin/repair-version.py')
    versioning = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(versioning)
    try:
        version = versioning.current_version(args.order)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'{exc}\n')
    profile = json.loads(args.profile.read_text())
    template = json.loads((KIT.parent / 'single-task-template.json').read_text())
    protocol = profile['protocol']
    template.update(purpose='Single-task repair from the active frozen-v3 baseline; new immutable development condition.')
    template['model'] = profile['model']
    template['protocol'].update(protocol)
    template['sources'] = {
        'development_workspace': str(ROOT / 'src/adapter_versions/v2_expanded'),
        'baseline_candidate': False, 'resume': False,
        'baseline_source_commit': profile['baseline']['source_commit'],
        'baseline_source_sha256': profile['baseline']['source_tree_sha256'],
        'completion_protocol': 'original v3 until explicitly modified in active source',
    }
    with tempfile.TemporaryDirectory(prefix='liteagent-prepare-') as temporary:
        base = Path(temporary) / 'template.json'
        dump(base, template)
        job = Path(subprocess.check_output([
            sys.executable, str(KIT), '--workspace', str(ROOT), '--order', str(args.order),
            '--owner', args.owner, '--base-config', str(base),
            '--job-root', profile['paths']['job_root'],
            '--max-steps', str(protocol['max_steps']),
            '--max-local-steps', str(protocol['max_local_steps']),
            '--max-agent-seconds', str(protocol['max_agent_seconds']),
        ], text=True).strip())
    command = json.loads((job / 'command.json').read_text())
    for flag, value in {
        '--model': profile['model']['requested'],
        '--base-url': profile['model']['base_urls'][0],
        '--reasoning-mode': profile['model']['reasoning_mode'],
        '--qcow2': profile['paths']['qcow2'],
        '--max-soft-restarts': protocol['max_soft_restarts'],
        '--max-no-progress-steps': protocol['max_no_progress_steps'],
        '--max-output-tokens': protocol['max_output_tokens'],
        '--request-timeout': protocol['request_timeout'],
        '--model-retries': protocol['model_retries'],
        '--top-k': protocol['top_k'], '--temperature': protocol['temperature'],
    }.items():
        command[command.index(flag) + 1] = str(value)
    command.extend(['--initial-step-budget', str(protocol['initial_step_budget'])])
    if protocol['thinking']:
        command.append('--thinking')
    dump(job / 'command.json', command)
    (job / 'command.sha256').write_text(hashlib.sha256((job / 'command.json').read_bytes()).hexdigest() + '\n')
    dump(job / 'selected-profile.json', profile)
    spec = importlib.util.spec_from_file_location('snapshot_seal', job / 'source/src/adapter_versions/v2_expanded/scripts/condition_seal.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    actual = module.build_source_tree_seal(job / 'source/src/adapter_versions/v2_expanded')
    dump(job / 'baseline-comparison.json', {
        'actual_runtime_seal': actual,
        'equals_frozen_v3': actual['sha256'] == profile['baseline']['source_tree_sha256'],
        'baseline_source_commit': profile['baseline']['source_commit'],
        'note': 'A future repair may differ; actual immutable snapshot identity is always recorded.',
    })
    subprocess.run([sys.executable, str(KIT), '--verify-job', str(job)], check=True)
    versioning.link_job(args.order, job, version)
    current = {'profile': str(args.profile.resolve()), 'order': args.order, 'prepared_job': str(job),
               'source_workspace': str(ROOT), 'baseline_comparison': json.loads((job / 'baseline-comparison.json').read_text()),
               'vm_started': False, 'status': 'prepared_only', 'repair_version': version}
    dump(ROOT / 'configs/current-single-task.json', current)
    print(job)


if __name__ == '__main__':
    main()

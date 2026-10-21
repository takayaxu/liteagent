#!/usr/bin/env python3
"""Save repair checkpoints and commits; revert the latest repair without deleting evidence."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent.parent


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT).decode().strip()


def config():
    return json.loads((ROOT / 'configs/repair-versioning.json').read_text())


def managed_changes():
    return git('status', '--porcelain=v1', '--untracked-files=all', '--', *config()['managed_paths'])


def require_clean():
    if managed_changes():
        raise RuntimeError('Managed source/config has uncommitted changes. Save it before checkpoint or prepare.')


def require_empty_index():
    if git('diff', '--cached', '--name-only'):
        raise RuntimeError('The Git index already contains staged changes; preserve them separately first.')


def stamp():
    return datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


def record(action, **values):
    ledger = Path(config()['ledger_root']).resolve()
    if ledger.is_relative_to(ROOT):
        raise RuntimeError('Repair evidence must be outside the source repository.')
    ledger.mkdir(parents=True, exist_ok=True)
    entry = {'action': action, 'recorded_at_utc': datetime.now(timezone.utc).isoformat(),
             'workspace': str(ROOT), 'branch': git('branch', '--show-current'), **values}
    write_json(ledger / f'{stamp()}-{action}.json', entry)
    return entry


def checkpoint_file():
    return Path(git('rev-parse', '--absolute-git-dir')) / 'liteagent-repair-checkpoint.json'


def current_version(order):
    require_clean()
    path = checkpoint_file()
    if not path.exists():
        raise RuntimeError(f'Create a checkpoint first: python bin/repair-version.py checkpoint --order {order}')
    checkpoint = json.loads(path.read_text())
    branch = git('branch', '--show-current')
    if checkpoint['order'] != order or checkpoint['branch'] != branch:
        raise RuntimeError('Checkpoint order/branch differs from the requested task; create its checkpoint first.')
    head = git('rev-parse', 'HEAD')
    if git('rev-parse', checkpoint['tag'] + '^{}') != checkpoint['commit']:
        raise RuntimeError('Checkpoint tag changed.')
    subprocess.run(['git', 'merge-base', '--is-ancestor', checkpoint['commit'], head],
                   cwd=ROOT, check=True)
    return {'order': order, 'branch': branch, 'commit': head,
            'checkpoint': checkpoint, 'managed_source_clean': True}


def checkpoint(order):
    require_clean()
    require_empty_index()
    branch = git('branch', '--show-current')
    if not branch:
        raise RuntimeError('A named repair branch is required.')
    head = git('rev-parse', 'HEAD')
    tag = f'checkpoint/order{order:03d}/{stamp()}'
    git('tag', '-a', tag, '-m', f'Before Order {order} repair', head)
    value = {'order': order, 'branch': branch, 'commit': head, 'tag': tag}
    write_json(checkpoint_file(), value)
    return record('checkpoint', **value)


def save(order, message):
    require_empty_index()
    # Saving is the one operation that accepts dirty managed files.
    path = checkpoint_file()
    if not path.exists():
        raise RuntimeError('Create a checkpoint before editing.')
    cp = json.loads(path.read_text())
    if cp['order'] != order or cp['branch'] != git('branch', '--show-current'):
        raise RuntimeError('Checkpoint order/branch does not match.')
    if git('rev-parse', cp['tag'] + '^{}') != cp['commit']:
        raise RuntimeError('Checkpoint tag changed.')
    subprocess.run(['git', 'merge-base', '--is-ancestor', cp['commit'], 'HEAD'], cwd=ROOT, check=True)
    if not managed_changes():
        raise RuntimeError('No managed changes to commit.')
    git('add', '-A', '--', *config()['managed_paths'])
    git('commit', '-m', f'fix(order{order:03d}): {message}', '-m', f'LiteAgent-Order: {order}')
    return record('save', order=order, commit=git('rev-parse', 'HEAD'), checkpoint=cp)


def link_job(order, job, expected):
    actual = current_version(order)
    if actual != expected:
        raise RuntimeError('Git version/checkpoint changed during preparation; retain this job and prepare again.')
    write_json(job / 'repair-version.json', actual)
    return record('prepare', **actual, job=str(job.resolve()))


def rollback(order, commit):
    version = current_version(order)
    require_empty_index()
    target = git('rev-parse', '--verify', f'{commit}^{{commit}}')
    if target != version['commit'] or target == version['checkpoint']['commit']:
        raise RuntimeError('Only the latest repair commit after this checkpoint may be reverted.')
    parents = git('rev-list', '--parents', '-n', '1', target).split()
    if len(parents) != 2:
        raise RuntimeError('Only a normal single-parent repair commit may be reverted.')
    if f'LiteAgent-Order: {order}' not in git('show', '-s', '--format=%B', target).splitlines():
        raise RuntimeError('Target is not a repair commit for this Order.')
    changed = git('diff-tree', '--no-commit-id', '--name-only', '-r', target).splitlines()
    paths = config()['managed_paths']
    if any(not any(p == scope or p.startswith(scope + '/') for scope in paths) for p in changed):
        raise RuntimeError('Target includes files outside the managed repair scope.')
    git('revert', '--no-edit', target)
    return record('rollback', order=order, reverted_commit=target,
                  commit=git('rev-parse', 'HEAD'), checkpoint=version['checkpoint'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    subs = parser.add_subparsers(dest='action', required=True)
    for action in ('checkpoint', 'save', 'rollback'):
        sub = subs.add_parser(action)
        sub.add_argument('--order', required=True, type=int, choices=range(1, 190), metavar='1..189')
        if action == 'save':
            sub.add_argument('--message', required=True)
        if action == 'rollback':
            sub.add_argument('--commit', required=True)
    args = parser.parse_args()
    try:
        if args.action == 'checkpoint':
            value = checkpoint(args.order)
        elif args.action == 'save':
            value = save(args.order, args.message)
        else:
            value = rollback(args.order, args.commit)
    except (RuntimeError, subprocess.CalledProcessError) as exc:
        parser.exit(1, f'{exc}\n')
    print(json.dumps(value, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

#!/usr/bin/env python3
"""Copy only project-owned files with a restoration manifest. No service changes."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

UUID = 'gnome-airpods-companion@dosment.github.io'


def install_project(source, prefix, state):
    source, prefix = Path(source).absolute(), Path(prefix).absolute()
    required = ['bin/gnome-airpods-companion', 'companion/__init__.py',
                'extension/metadata.json', 'extension/extension.js',
                'systemd/gnome-airpods-companion.service']
    for relative in required:
        if not (source / relative).is_file():
            raise RuntimeError(f'Incomplete build: {relative}')
    metadata = json.loads((source / 'extension/metadata.json').read_text())
    if metadata.get('uuid') != UUID:
        raise RuntimeError('Extension UUID does not match installer')
    app = prefix / 'share/gnome-airpods-companion'
    files = []
    for directory in ('bin', 'companion', 'extension', 'systemd'):
        destination = {'bin': app / 'bin', 'companion': app / 'companion',
                       'extension': prefix / 'share/gnome-shell/extensions' / UUID,
                       'systemd': prefix / 'share/systemd/user'}[directory]
        for path in sorted((source / directory).rglob('*')):
            if '__pycache__' in path.parts or path.suffix == '.pyc':
                continue
            if path.is_file():
                files.append((path, destination / path.relative_to(source / directory)))
    with tempfile.TemporaryDirectory() as temporary:
        launcher = Path(temporary) / 'launcher'
        command = str(app / 'bin/gnome-airpods-companion')
        launcher.write_text('#!/usr/bin/env python3\nimport os, sys\nos.execv(sys.executable, [sys.executable, ' + repr(command) + '] + sys.argv[1:])\n')
        launcher.chmod(0o755)
        files.append((launcher, prefix / 'bin/gnome-airpods-companion'))
        install_files(files, state)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def install_files(files, state):
    files = [(Path(source).absolute(), Path(target).absolute()) for source, target in files]
    for source, target in files:
        if not source.is_file() or source.is_symlink():
            raise RuntimeError(f'Missing or symlink source: {source}')
        if any(p.is_symlink() for p in (target, *target.parents)):
            raise RuntimeError(f'Refusing symlink target or ancestor: {target}')
        if target.exists() and not target.is_file():
            raise RuntimeError(f'Target is not a regular file: {target}')
    state = Path(state).absolute()
    if any(p.is_symlink() for p in (state, *state.parents)):
        raise RuntimeError('Refusing symlink state directory')
    state.mkdir(parents=True, exist_ok=False, mode=0o700)
    records = []
    try:
        for number, (source, target) in enumerate(files):
            record = {'target': str(target), 'hash': digest(source), 'backup': None}
            if target.exists():
                backup = state / str(number)
                shutil.copy2(target, backup)
                record['backup'] = str(backup)
            records.append(record)
            # Save recovery metadata before changing each target.
            (state / 'manifest.json').write_text(json.dumps(records, indent=2))
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
    except Exception:
        for record in reversed(records):
            target = Path(record['target'])
            if record['backup']:
                shutil.copy2(record['backup'], target)
            else:
                target.unlink(missing_ok=True)
        shutil.rmtree(state)
        raise


def uninstall_files(state):
    state = Path(state)
    records = json.loads((state / 'manifest.json').read_text())
    for record in records:
        target = Path(record['target'])
        if target.is_symlink() or not target.is_file() or digest(target) != record['hash']:
            raise RuntimeError(f'Installed file modified or missing; preserve it and resolve before uninstall: {target}')
    for record in reversed(records):
        target = Path(record['target'])
        if record['backup']:
            shutil.copy2(record['backup'], target)
        else:
            target.unlink(missing_ok=True)
    shutil.rmtree(state)


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install', 'uninstall'])
    parser.add_argument('--prefix', type=Path, default=Path.home() / '.local')
    parser.add_argument('--state', type=Path, default=Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'gnome-airpods-companion/install')
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error('Run as your desktop user, never sudo.')
    try:
        if args.action == 'install':
            install_project(Path(__file__).resolve().parents[1], args.prefix, args.state)
            print('Files installed. No services enabled or audio configuration changed.')
        else:
            uninstall_files(args.state)
            print('Project files removed and prior files restored. User configuration retained.')
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()

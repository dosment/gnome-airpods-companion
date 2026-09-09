#!/usr/bin/env python3
"""Install the locally compiled, version-pinned controls daemon; never activate it."""
import json
from pathlib import Path

REVISION = 'fff7fec600a5b9a61cdb40e93eccbcceb4b8f824'


def payload(work, prefix, root):
    work, prefix, root = Path(work), Path(prefix), Path(root)
    receipt = json.loads((work / 'provenance.json').read_text())
    if receipt.get('built') is not True:
        raise RuntimeError('Daemon has not been built successfully')
    if receipt.get('revision') != REVISION:
        raise RuntimeError('Unexpected upstream revision')
    import hashlib
    patch = root / 'patches/0001-controls-only.patch'
    if receipt.get('patch_sha256') != hashlib.sha256(patch.read_bytes()).hexdigest():
        raise RuntimeError('Build patch differs from reviewed project patch')
    app = prefix / 'share/gnome-airpods-companion'
    files = [(work / 'build' / name, app / 'libexec' / name)
             for name in ('librepods', 'librepods-ctl')]
    files.extend((work / 'source/daemon' / name, app / 'upstream' / name)
                 for name in ('LICENSE', 'UPSTREAM.md'))
    files.extend([(patch, app / 'upstream' / patch.name),
                  (work / 'provenance.json', app / 'upstream/provenance.json'),
                  (root / 'templates/gnome-airpods-controls.service', prefix / 'share/systemd/user/gnome-airpods-controls.service')])
    for source, _ in files:
        if not source.is_file() or source.is_symlink():
            raise RuntimeError(f'Missing or symlink build artifact: {source}')
    for binary in (work / 'build/librepods', work / 'build/librepods-ctl'):
        if not binary.stat().st_mode & 0o111:
            raise RuntimeError(f'Build artifact is not executable: {binary}')
    return files


def main():
    import argparse
    import importlib.util
    import os
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=['install', 'uninstall'])
    parser.add_argument('--work', type=Path, help='Successful builder work directory (required for install)')
    parser.add_argument('--prefix', type=Path, default=Path.home() / '.local')
    parser.add_argument('--state', type=Path, default=Path(os.environ.get('XDG_STATE_HOME', str(Path.home() / '.local/state'))) / 'gnome-airpods-companion/apple-install')
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error('Run as the desktop user, never sudo.')
    root = Path(__file__).resolve().parents[1]
    spec = importlib.util.spec_from_file_location('file_installer', root / 'scripts/manage-install.py')
    assert spec and spec.loader
    manager = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(manager)
    try:
        if args.action == 'install':
            if args.work is None:
                parser.error('--work is required for install')
            manager.install_files(payload(args.work, args.prefix, root), args.state)
            print('Controls daemon files installed. No service started; no Bluetooth changes.')
        else:
            manager.uninstall_files(args.state)
            print('Controls daemon files restored/removed; private pairing configuration retained.')
    except (OSError, RuntimeError, ValueError) as error:
        parser.exit(1, f'{error}\n')


if __name__ == '__main__':
    main()

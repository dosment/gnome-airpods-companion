#!/usr/bin/env python3
"""Fetch exact source, patch, test and build in private cache; NEVER install/run.

Use --prepare-only when Qt/build dependencies are unavailable. JSON on stdout;
progress and build output on stderr. Each run gets a fresh retained directory.
"""
import argparse
import hashlib
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile

REVISION = 'fff7fec600a5b9a61cdb40e93eccbcceb4b8f824'
URL = 'https://github.com/thisisgm/omarchy-pods.git'
APT = ('build-essential git cmake ninja-build pkg-config qt6-base-dev '
       'qt6-declarative-dev qt6-connectivity-dev qt6-tools-dev '
       'qt6-tools-dev-tools libpulse-dev libssl-dev')


def run(*args, cwd=None, capture=False):
    result = subprocess.run(args, cwd=cwd, check=True, stdout=subprocess.PIPE if capture else sys.stderr)
    return result.stdout if capture else b''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only', action='store_true')
    args = parser.parse_args()
    if os.geteuid() == 0:
        parser.error('Do not run this builder as root.')
    os.umask(0o077)
    root = Path(__file__).resolve().parents[1]
    cache = Path.home() / '.cache/gnome-airpods-companion'
    cache.mkdir(parents=True, exist_ok=True)
    upstream = cache / 'upstream'
    if not upstream.exists():
        run('git', 'clone', '--no-checkout', URL, str(upstream))
    origin = run('git', 'remote', 'get-url', 'origin', cwd=upstream, capture=True).decode().strip()
    if origin != URL:
        raise RuntimeError('Cached upstream origin does not match pinned provenance')
    probe = subprocess.run(['git', 'cat-file', '-e', REVISION + '^{commit}'], cwd=upstream, capture_output=True)
    if probe.returncode:
        run('git', 'fetch', '--depth=1', 'origin', REVISION, cwd=upstream)
    # Archive the object, never reuse a dirty worktree or remove another run.
    archive = run('git', 'archive', '--format=tar', REVISION, 'daemon', cwd=upstream, capture=True)
    work = Path(tempfile.mkdtemp(prefix='build-' + REVISION[:12] + '-', dir=cache))
    source = work / 'source'
    source.mkdir()
    with tarfile.open(fileobj=io.BytesIO(archive)) as tf:
        tf.extractall(source, filter='data')
    patch = root / 'patches/0001-controls-only.patch'
    run('git', 'apply', '--check', str(patch), cwd=source)
    run('git', 'apply', str(patch), cwd=source)
    run(sys.executable, str(root / 'patches/test_controls_only.py'), str(source))
    shutil.copy2(patch, work / patch.name)
    shutil.copy2(__file__, work / 'build-librepods.py')
    result = {'revision': REVISION, 'upstream': URL, 'source': str(source),
              'work': str(work), 'patch_sha256': hashlib.sha256(patch.read_bytes()).hexdigest(),
              'built': False, 'installed': False}
    if not args.prepare_only:
        missing = [cmd for cmd in ('cmake', 'ninja', 'pkg-config', 'g++') if not shutil.which(cmd)]
        if missing:
            result['error'] = 'Missing build commands: ' + ', '.join(missing)
            result['apt_dependencies'] = APT
            (work / 'provenance.json').write_text(json.dumps(result, indent=2) + '\n')
            print(json.dumps(result, indent=2))
            return 2
        build = work / 'build'
        # Build the two binaries only. No install target, services, or runtime tests.
        run('cmake', '-S', str(source / 'daemon'), '-B', str(build), '-G', 'Ninja',
            '-DCMAKE_BUILD_TYPE=Release', '-DCMAKE_CXX_STANDARD=17',
            '-DBUILD_TESTING=OFF', '-DCMAKE_INSTALL_BINDIR=bin')
        run('cmake', '--build', str(build), '--target', 'librepods', 'librepods-ctl', '--parallel', '2')
        for binary in ('librepods', 'librepods-ctl'):
            if not (build / binary).is_file():
                raise RuntimeError('Build did not produce ' + binary)
        result.update(built=True, binaries=[str(build / b) for b in ('librepods', 'librepods-ctl')])
    (work / 'provenance.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)

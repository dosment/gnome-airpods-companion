"""Only fixture files are installed; no daemon or service is started."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def load():
    path = ROOT / 'scripts/install-librepods.py'
    if not path.exists():
        raise AssertionError('Apple backend installer not implemented')
    spec = importlib.util.spec_from_file_location('apple_install', path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class AppleInstallTest(unittest.TestCase):
    def test_unbuilt_or_wrong_revision_is_rejected_before_writes(self):
        m = load()
        with tempfile.TemporaryDirectory() as tmp:
            work = Path(tmp) / 'work'
            work.mkdir()
            (work / 'provenance.json').write_text(json.dumps({'built': False}))
            with self.assertRaisesRegex(RuntimeError, 'built'):
                m.payload(work, Path(tmp) / 'prefix', ROOT)
            (work / 'provenance.json').write_text(json.dumps({'built': True, 'revision': 'wrong'}))
            with self.assertRaisesRegex(RuntimeError, 'revision'):
                m.payload(work, Path(tmp) / 'prefix', ROOT)

    def test_cli_help_documents_separate_activation(self):
        import subprocess
        result = subprocess.run(['python3', str(ROOT / 'scripts/install-librepods.py'), '--help'], text=True, capture_output=True, check=True)
        self.assertIn('--work', result.stdout)
        self.assertIn('uninstall', result.stdout)

    def test_payload_is_scoped_and_patch_verified(self):
        import hashlib
        m = load()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            work, root, prefix = base / 'work', base / 'project', base / 'prefix'
            for directory in (work / 'build', work / 'source/daemon', root / 'patches', root / 'templates'):
                directory.mkdir(parents=True)
            patch = root / 'patches/0001-controls-only.patch'
            patch.write_text('fixture patch')
            (work / 'provenance.json').write_text(json.dumps({'built': True, 'revision': m.REVISION, 'patch_sha256': hashlib.sha256(patch.read_bytes()).hexdigest()}))
            for name in ('librepods', 'librepods-ctl'):
                p = work / 'build' / name
                p.write_text('fixture binary')
                p.chmod(0o700)
            for name in ('LICENSE', 'UPSTREAM.md'):
                (work / 'source/daemon' / name).write_text('fixture notice')
            (root / 'templates/gnome-airpods-controls.service').write_text('fixture unit')
            files = m.payload(work, prefix, root)
            targets = {str(dst.relative_to(prefix)) for _, dst in files}
            self.assertIn('share/gnome-airpods-companion/libexec/librepods-ctl', targets)
            self.assertIn('share/systemd/user/gnome-airpods-controls.service', targets)
            self.assertNotIn('bin/librepods', targets)
            self.assertFalse(prefix.exists())
            patch.write_text('changed after build')
            with self.assertRaisesRegex(RuntimeError, 'patch'):
                m.payload(work, prefix, root)


if __name__ == '__main__':
    unittest.main()

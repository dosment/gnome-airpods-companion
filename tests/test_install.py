"""Installer behavior in temporary prefixes; never touches desktop services."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


def installer():
    path = ROOT / 'scripts' / 'manage-install.py'
    if not path.exists():
        raise AssertionError('reversible installer is not implemented')
    spec = importlib.util.spec_from_file_location('installer', path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class InstallerTests(unittest.TestCase):
    def test_install_and_uninstall_preserves_prior_file(self):
        m = installer()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / 'source'
            source.mkdir()
            (source / 'hello').write_text('new')
            target = base / 'prefix'
            target.mkdir()
            (target / 'hello').write_text('original')
            (target / 'hello').chmod(0o640)
            state = base / 'state'
            m.install_files([(source / 'hello', target / 'hello')], state)
            self.assertEqual((target / 'hello').read_text(), 'new')
            m.uninstall_files(state)
            self.assertEqual((target / 'hello').read_text(), 'original')
            self.assertEqual((target / 'hello').stat().st_mode & 0o777, 0o640)

    def test_cli_help_exposes_install_and_uninstall(self):
        import subprocess
        result = subprocess.run(['python3', str(ROOT / 'scripts/manage-install.py'), '--help'], text=True, capture_output=True, check=True)
        self.assertIn('uninstall', result.stdout)
        self.assertIn('--prefix', result.stdout)

    def test_project_install_runs_launcher_and_removes_owned_files(self):
        import subprocess
        m = installer()
        self.assertTrue(hasattr(m, 'install_project'), 'project packaging is not implemented')
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / 'source'
            for directory in ('bin', 'companion', 'extension', 'systemd'):
                (source / directory).mkdir(parents=True)
            (source / 'bin/gnome-airpods-companion').write_text('print("fixture backend")\n')
            (source / 'companion/__init__.py').write_text('')
            (source / 'extension/metadata.json').write_text('{"uuid":"gnome-airpods-companion@dosment.github.io"}')
            (source / 'extension/extension.js').write_text('// fixture')
            (source / 'systemd/gnome-airpods-companion.service').write_text('[Service]\nExecStart=/bin/true\n')
            prefix, state = base / 'local prefix', base / 'state'
            m.install_project(source, prefix, state)
            launcher = prefix / 'bin/gnome-airpods-companion'
            result = subprocess.run([str(launcher), 'status'], text=True, capture_output=True, check=True)
            self.assertEqual(result.stdout.strip(), 'fixture backend')
            self.assertTrue((prefix / 'share/gnome-shell/extensions/gnome-airpods-companion@dosment.github.io/extension.js').exists())
            m.uninstall_files(state)
            self.assertFalse(launcher.exists())

    def test_copy_failure_rolls_back_prior_changes(self):
        from unittest.mock import patch
        m = installer()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / 'source'
            source.write_text('new')
            first, second = base / 'first', base / 'second'
            first.write_text('old')
            original_copy = m.shutil.copy2
            def fail_second(src, dst, *args, **kwargs):
                if Path(dst) == second:
                    raise OSError('simulated disk failure')
                return original_copy(src, dst, *args, **kwargs)
            with patch.object(m.shutil, 'copy2', side_effect=fail_second):
                with self.assertRaises(OSError):
                    m.install_files([(source, first), (source, second)], base / 'state')
            self.assertEqual(first.read_text(), 'old')
            self.assertFalse(second.exists())
            self.assertFalse((base / 'state').exists())

    def test_install_preflights_all_sources_and_symlink_targets(self):
        m = installer()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / 'source'
            source.write_text('new')
            target = base / 'target'
            target.write_text('old')
            with self.assertRaises((RuntimeError, FileNotFoundError)):
                m.install_files([(source, target), (base / 'missing', base / 'other')], base / 'state')
            self.assertEqual(target.read_text(), 'old')
            self.assertFalse((base / 'state').exists())
            link = base / 'link'
            link.symlink_to(target)
            with self.assertRaisesRegex(RuntimeError, 'symlink'):
                m.install_files([(source, link)], base / 'state')
            self.assertEqual(target.read_text(), 'old')

    def test_uninstall_refuses_modified_file_before_restoring_anything(self):
        m = installer()
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / 'source'
            source.write_text('installed')
            first, second = base / 'first', base / 'second'
            state = base / 'state'
            m.install_files([(source, first), (source, second)], state)
            first.write_text('human change')
            with self.assertRaisesRegex(RuntimeError, 'modified'):
                m.uninstall_files(state)
            self.assertEqual(first.read_text(), 'human change')
            self.assertEqual(second.read_text(), 'installed')
            self.assertTrue((state / 'manifest.json').exists())


if __name__ == '__main__':
    unittest.main()

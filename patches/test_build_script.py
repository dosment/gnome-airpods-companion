#!/usr/bin/env python3
"""Offline smoke test after upstream has been cached. Never starts daemon."""
import json
import pathlib
import subprocess
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]


class SafePreparation(unittest.TestCase):
    def test_prepare_pinned_source_without_build_or_install(self):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/build-librepods.py'), '--prepare-only'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['revision'], 'fff7fec600a5b9a61cdb40e93eccbcceb4b8f824')
        self.assertFalse(data['built'])
        self.assertFalse(data['installed'])
        source = pathlib.Path(data['source'])
        self.assertTrue(source.is_relative_to(pathlib.Path.home() / '.cache/gnome-airpods-companion'))
        self.assertTrue((source / 'daemon/LICENSE').is_file())
        subprocess.run([sys.executable, str(ROOT / 'patches/test_controls_only.py'), str(source)], check=True)


if __name__ == '__main__':
    unittest.main()

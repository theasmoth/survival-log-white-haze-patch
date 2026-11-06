"""CLI tests on synthetic files; never modify the installed game."""
import hashlib
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('patch_vuplex.py')
ORIGINAL = b'MZ-test-\x0f\x85\xf1\x00\x00\x00-end'
PATCHED = b'MZ-test-\x0f\x85\x00\x00\x00\x00-end'


class PatchTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dll = Path(self.tmp.name) / 'plugin.dll'
        self.dll.write_bytes(ORIGINAL)
        self.backup = Path(str(self.dll) + '.original.bak')

    def run_cli(self, action, *extra):
        return subprocess.run([
            sys.executable, str(SCRIPT), action, '--dll', str(self.dll),
            '--offset', '0xA', '--before', 'f1', '--after', '00',
            '--original-sha256', hashlib.sha256(ORIGINAL).hexdigest(),
            '--patched-sha256', hashlib.sha256(PATCHED).hexdigest(), *extra,
        ], capture_output=True, text=True)

    def test_patch_and_restore_preserve_original(self):
        result = self.run_cli('patch')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.dll.read_bytes(), PATCHED)
        self.assertEqual(self.backup.read_bytes(), ORIGINAL)
        result = self.run_cli('restore')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.dll.read_bytes(), ORIGINAL)
        self.assertEqual(self.backup.read_bytes(), ORIGINAL)

    def test_patch_restore_patch_reuses_verified_backup(self):
        for action in ('patch', 'restore'):
            result = self.run_cli(action)
            self.assertEqual(result.returncode, 0, result.stderr)
        before = self.backup.stat()
        result = self.run_cli('patch')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.dll.read_bytes(), PATCHED)
        self.assertEqual(self.backup.read_bytes(), ORIGINAL)
        self.assertEqual(self.backup.stat().st_ino, before.st_ino)
        self.assertEqual(self.backup.stat().st_mtime_ns, before.st_mtime_ns)

    def test_unknown_version_is_untouched(self):
        self.dll.write_bytes(b'other version')
        self.assertNotEqual(self.run_cli('patch').returncode, 0)
        self.assertEqual(self.dll.read_bytes(), b'other version')
        self.assertFalse(self.backup.exists())

    def test_existing_backup_is_never_overwritten(self):
        self.backup.write_bytes(b'precious backup')
        self.assertNotEqual(self.run_cli('patch').returncode, 0)
        self.assertEqual(self.backup.read_bytes(), b'precious backup')
        self.assertEqual(self.dll.read_bytes(), ORIGINAL)

    def test_dry_run_does_not_write(self):
        result = self.run_cli('patch', '--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.dll.read_bytes(), ORIGINAL)
        self.assertFalse(self.backup.exists())

    def test_repeat_patch_is_idempotent(self):
        self.assertEqual(self.run_cli('patch').returncode, 0)
        result = self.run_cli('patch')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.dll.read_bytes(), PATCHED)
        self.assertEqual(self.backup.read_bytes(), ORIGINAL)

    def test_restore_refuses_corrupt_backup(self):
        self.assertEqual(self.run_cli('patch').returncode, 0)
        self.backup.write_bytes(b'corrupt')
        self.assertNotEqual(self.run_cli('restore').returncode, 0)
        self.assertEqual(self.dll.read_bytes(), PATCHED)

    def test_wrong_output_hash_does_not_write(self):
        result = self.run_cli('patch', '--patched-sha256', 'a' * 64)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.dll.read_bytes(), ORIGINAL)
        self.assertFalse(self.backup.exists())

    def test_wrong_expected_bytes_does_not_write(self):
        self.assertNotEqual(self.run_cli('patch', '--before', 'ff').returncode, 0)
        self.assertEqual(self.dll.read_bytes(), ORIGINAL)
        self.assertFalse(self.backup.exists())

    def test_patch_does_not_inspect_processes(self):
        # Process inspection must not be required for file patching.
        code = """
import runpy
import subprocess
import sys

def forbidden(*args, **kwargs):
    raise RuntimeError('Unexpected process inspection')

subprocess.run = forbidden
subprocess.check_output = forbidden
subprocess.Popen = forbidden
sys.argv = sys.argv[1:]
runpy.run_path(sys.argv[0], run_name='__main__')
"""
        result = subprocess.run([
            sys.executable, '-c', code, str(SCRIPT), 'patch', '--dll', str(self.dll),
            '--offset', '0xA', '--before', 'f1', '--after', '00',
            '--original-sha256', hashlib.sha256(ORIGINAL).hexdigest(),
            '--patched-sha256', hashlib.sha256(PATCHED).hexdigest(),
        ], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.dll.read_bytes(), PATCHED)

    def test_restore_requires_backup(self):
        self.dll.write_bytes(PATCHED)
        self.assertNotEqual(self.run_cli('restore').returncode, 0)
        self.assertEqual(self.dll.read_bytes(), PATCHED)

    def discover_cli(self, action='status'):
        return subprocess.run([
            sys.executable, str(SCRIPT), action,
            '--bottles-dir', str(Path(self.tmp.name) / 'Bottles'),
            '--offset', '0xA', '--before', 'f1', '--after', '00',
            '--original-sha256', hashlib.sha256(ORIGINAL).hexdigest(),
            '--patched-sha256', hashlib.sha256(PATCHED).hexdigest(),
        ], capture_output=True, text=True)

    def make_install(self, bottle, data=ORIGINAL):
        game = Path(self.tmp.name) / 'Bottles' / bottle / 'drive_c/Games/Survival Log'
        dll = game / 'SurvivalLog_Data/Plugins/x86_64/VuplexWebViewWindows.dll'
        dll.parent.mkdir(parents=True)
        dll.write_bytes(data)
        (game / 'SurvivalLog.exe').write_bytes(b'fixture')
        return dll

    def test_discovery_patches_and_restores_unique_install(self):
        dll = self.make_install('one')
        result = self.discover_cli('patch')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(dll.read_bytes(), PATCHED)
        result = self.discover_cli('restore')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(dll.read_bytes(), ORIGINAL)

    def test_discovery_refuses_ambiguous_installs(self):
        one = self.make_install('one')
        two = self.make_install('two', PATCHED)
        result = self.discover_cli('patch')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('Multiple supported', result.stderr)
        self.assertEqual(one.read_bytes(), ORIGINAL)
        self.assertEqual(two.read_bytes(), PATCHED)

    def test_discovery_refuses_unknown_version(self):
        dll = self.make_install('one', b'unknown')
        result = self.discover_cli('patch')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('No supported', result.stderr)
        self.assertEqual(dll.read_bytes(), b'unknown')

    def test_discovery_does_not_follow_directory_symlinks(self):
        root = Path(self.tmp.name) / 'Bottles'
        root.mkdir()
        (root / 'linked').symlink_to(Path(self.tmp.name), target_is_directory=True)
        result = self.discover_cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('No supported', result.stderr)

    def test_status_does_not_write(self):
        self.assertEqual(self.run_cli('status').returncode, 0)
        self.assertFalse(self.backup.exists())


if __name__ == '__main__':
    unittest.main()

import importlib.util
from pathlib import Path
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('vault', Path(__file__).resolve().parents[1] / 'deploy/recovery/vault.py')
vault = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vault)


class VaultTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.root.chmod(0o700)
        self.good = self.root / 'export-retained.age'
        self.good.write_bytes(b'age-encryption.org/v1\nretained')
        self.good.chmod(0o600)

    def transfer(self, data, failure=None):
        def run(args, **kwargs):
            kwargs['stdout'].write(data)
            if failure:
                raise failure
            return subprocess.CompletedProcess(args, 0)
        return patch.object(vault.subprocess, 'run', side_effect=run)

    def test_atomic_copy_modes_and_no_overwrite(self):
        with self.transfer(b'age-encryption.org/v1\nnew'):
            vault.collect('pink-party', 'export-new', self.root)
            with self.assertRaises(ValueError):
                vault.collect('pink-party', 'export-new', self.root)
        target = self.root / 'export-new.age'
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(target.stat().st_nlink, 1)
        self.assertEqual(self.good.read_bytes(), b'age-encryption.org/v1\nretained')

    def test_failed_truncated_oversized_or_interrupted_transfer_preserves_prior(self):
        for data, error in [(b'truncated', None), (b'x' * (vault.LIMIT + 1), None),
                            (b'age-encryption.org/v1\npartial', subprocess.TimeoutExpired('transfer', 30)),
                            (b'age-encryption.org/v1\npartial', KeyboardInterrupt())]:
            with self.subTest(error=type(error).__name__), self.transfer(data, error):
                with self.assertRaises((ValueError, subprocess.TimeoutExpired, KeyboardInterrupt)):
                    vault.collect('pink-party', 'export-new', self.root)
                self.assertFalse((self.root / 'export-new.age').exists())
                self.assertEqual(self.good.read_bytes(), b'age-encryption.org/v1\nretained')
                self.assertFalse(list(self.root.glob('.collect-*')))

    def test_full_vault_refuses_without_pruning(self):
        for index in range(vault.KEEP - 1):
            path = self.root / ('export-old' + str(index) + '.age')
            path.write_bytes(b'prior')
            path.chmod(0o600)
        before = {p.name: p.read_bytes() for p in self.root.glob('*.age')}
        with self.transfer(b'age-encryption.org/v1\nnew') as transfer:
            with self.assertRaisesRegex(ValueError, 'full'):
                vault.collect('pink-party', 'export-new', self.root)
            transfer.assert_not_called()
        self.assertEqual(before, {p.name: p.read_bytes() for p in self.root.glob('*.age')})

    def test_stale_publication_link_cleaned_before_next_transfer(self):
        stale = self.root / '.collect-interrupted'
        stale.mkdir(mode=0o700)
        os.link(self.good, stale / 'snapshot.age')
        with self.transfer(b'bad'):
            with self.assertRaises(ValueError):
                vault.collect('pink-party', 'export-new', self.root)
        self.assertFalse(stale.exists())
        self.assertEqual(self.good.stat().st_nlink, 1)


if __name__ == '__main__':
    unittest.main()

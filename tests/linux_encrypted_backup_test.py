import datetime as dt
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('encrypted_backup', Path(__file__).resolve().parents[1] / 'deploy/linux/encrypted-backup.py')
encrypted = importlib.util.module_from_spec(spec)
spec.loader.exec_module(encrypted)
backup = encrypted.backup


@unittest.skipUnless(shutil.which('age') and shutil.which('age-keygen'), 'Install age to run encryption integration boundaries')
class EncryptedBackupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.store, self.exports, self.work, self.restores, self.keys = [self.root / name for name in ['backups', 'exports', 'work', 'restores', 'keys']]
        for directory in [self.store, self.exports, self.work, self.restores, self.keys]:
            directory.mkdir(mode=0o700)
        self.identity = self.keys / 'identity.txt'
        subprocess.run(['age-keygen', '-o', str(self.identity)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.identity.chmod(0o600)
        self.recipient = self.keys / 'recipient.txt'
        result = subprocess.run(['age-keygen', '-y', str(self.identity)], check=True, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        backup.write_private(self.recipient, result.stdout)
        self.sources = {name: self.root / name.replace('/', '-') for name in backup.MODES}
        self.sources['data/session.json'].write_text(json.dumps({'synthetic': True, 'title': 'Synthetic encrypted recovery', 'game': 'Synthetic game', 'description': 'A synthetic off-VM recovery session.', 'startsAt': '2026-11-17T20:00:00+01:00', 'timeZone': 'Europe/Madrid', 'tag': 'Lab'}))
        self.sources['private/pink-party.env'].write_text('PINK_PARTY_MODE=local\nJOIN_CODE=' + 'j' * 24 + '\nLIVEKIT_API_KEY=' + 'k' * 24 + '\nLIVEKIT_API_SECRET=' + 's' * 64 + '\n')
        for name, source in self.sources.items():
            source.chmod(backup.MODES[name])
        self.snapshot = backup.create_backup(self.sources, self.store)[0]

    def export(self):
        return encrypted.export_backup(self.snapshot, self.exports, self.recipient) / 'snapshot.tar.age'

    def inventories(self):
        return {str(p.relative_to(self.exports)): p.read_bytes() for p in self.exports.rglob('*') if p.is_file()}

    def bad_archive(self, mutation):
        raw = (self.snapshot / 'snapshot.tar').read_bytes()
        output = io.BytesIO()
        with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as src, tarfile.open(fileobj=output, mode='w', format=tarfile.USTAR_FORMAT) as dest:
            for member in src:
                data = src.extractfile(member).read()
                if member.name == 'data/session.json':
                    if mutation == 'path':
                        member.name = '../escape'
                    elif mutation == 'schema':
                        data = b'{"synthetic":true}'
                    elif mutation == 'mode':
                        member.mode = 0o777
                elif mutation == 'schema' and member.name == 'manifest.json':
                    manifest = json.loads(data)
                    manifest['files']['data/session.json'].update(sha256=backup.digest(b'{"synthetic":true}'), bytes=len(b'{"synthetic":true}'))
                    data = json.dumps(manifest).encode()
                member.size = len(data)
                dest.addfile(member, io.BytesIO(data))
        return output.getvalue()

    def test_roundtrip_authenticates_then_restores_exact_bytes_modes(self):
        cipher = self.export()
        self.assertNotIn(self.sources['private/pink-party.env'].read_bytes(), cipher.read_bytes())
        self.assertEqual(cipher.stat().st_mode & 0o777, 0o600)
        self.assertEqual(cipher.parent.stat().st_mode & 0o777, 0o700)
        self.assertTrue(encrypted.verify_export(cipher, self.identity, self.work))
        destination = self.restores / 'recovered'
        encrypted.restore_export(cipher, destination, self.identity, self.work)
        for name, source in self.sources.items():
            self.assertEqual((destination / name).read_bytes(), source.read_bytes())
            self.assertEqual((destination / name).stat().st_mode & 0o777, backup.MODES[name])
        self.assertEqual(list(self.work.glob('.decrypt-*')), [])
        with self.assertRaisesRegex(ValueError, 'already exists'):
            encrypted.restore_export(cipher, destination, self.identity, self.work)
        self.assertEqual((destination / 'private/pink-party.env').read_bytes(), self.sources['private/pink-party.env'].read_bytes())

    def test_wrong_missing_and_unavailable_keys_never_publish(self):
        cipher = self.export()
        before = self.inventories()
        wrong = self.keys / 'wrong.txt'
        subprocess.run(['age-keygen', '-o', str(wrong)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        wrong.chmod(0o600)
        for key in [wrong, self.keys / 'missing.txt']:
            with self.assertRaises((ValueError, OSError)):
                encrypted.restore_export(cipher, self.restores / 'bad', key, self.work)
            self.assertFalse((self.restores / 'bad').exists())
        self.identity.chmod(0o000)
        with self.assertRaises((ValueError, OSError)):
            encrypted.verify_export(cipher, self.identity, self.work)
        self.identity.chmod(0o600)
        self.assertEqual(self.inventories(), before)
        self.assertTrue(encrypted.verify_export(cipher, self.identity, self.work))

    def test_corruption_truncation_and_oversize_rejected_before_publish(self):
        cipher = self.export()
        original = cipher.read_bytes()
        bad = self.exports / 'bad.age'
        for data in [original[:-1], original[:80], original[:-8] + b'broken!!', b'x' * (encrypted.CIPHER_LIMIT + 1)]:
            if bad.exists():
                bad.unlink()
            backup.write_private(bad, data)
            with self.assertRaises((ValueError, OSError)):
                encrypted.restore_export(bad, self.restores / 'bad', self.identity, self.work)
            self.assertFalse((self.restores / 'bad').exists())
            self.assertEqual(cipher.read_bytes(), original)
        self.assertEqual(list(self.work.glob('.decrypt-*')), [])

    def test_authenticated_invalid_archive_schema_paths_and_modes_rejected(self):
        cipher = self.export()
        before = cipher.read_bytes()
        bad = self.exports / 'invalid.age'
        for mutation in ['path', 'schema', 'mode', 'not-tar']:
            if bad.exists():
                bad.unlink()
            plaintext = b'synthetic invalid tar archive' if mutation == 'not-tar' else self.bad_archive(mutation)
            data = encrypted.age_transform(plaintext, ['--encrypt', '--recipient', encrypted.read_recipient(self.recipient)], self.work, encrypted.CIPHER_LIMIT)
            backup.write_private(bad, data)
            with self.assertRaises((ValueError, tarfile.TarError)):
                encrypted.restore_export(bad, self.restores / 'bad', self.identity, self.work)
            self.assertFalse((self.restores / 'bad').exists())
            self.assertEqual(cipher.read_bytes(), before)
        self.assertFalse((self.root / 'escape').exists())

    def test_failed_timed_out_and_interrupted_export_preserve_previous_copies(self):
        self.export()
        before = self.inventories()
        for failure in [ValueError('age operation failed; check key and encrypted input'), subprocess.TimeoutExpired('age', 15), KeyboardInterrupt()]:
            with patch.object(encrypted, 'age_transform', side_effect=failure):
                with self.assertRaises(type(failure)):
                    self.export()
            self.assertEqual(self.inventories(), before)
            self.assertEqual(list(self.exports.glob('.pending-export-*')), [])
        stale = self.exports / '.pending-export-interrupted'
        stale.mkdir(mode=0o700)
        backup.write_private(stale / 'partial', b'synthetic unfinished ciphertext')
        self.export()
        self.assertFalse(stale.exists())
        for path in before:
            self.assertEqual((self.exports / path).read_bytes(), before[path])

    def test_failed_and_interrupted_restore_never_publish(self):
        cipher = self.export()
        before = self.inventories()
        for failure in [ValueError('age operation failed; check key and encrypted input'), subprocess.TimeoutExpired('age', 15), KeyboardInterrupt()]:
            with patch.object(encrypted, 'age_transform', side_effect=failure):
                with self.assertRaises(type(failure)):
                    encrypted.restore_export(cipher, self.restores / 'bad', self.identity, self.work)
            self.assertFalse((self.restores / 'bad').exists())
            self.assertEqual(self.inventories(), before)
            self.assertEqual(list(self.work.glob('.decrypt-*')), [])
        stale = self.work / '.decrypt-interrupted'
        stale.mkdir(mode=0o700)
        backup.write_private(stale / 'partial', b'synthetic partial plaintext')
        self.assertTrue(encrypted.verify_export(cipher, self.identity, self.work))
        self.assertFalse(stale.exists())

    def test_restore_write_and_publication_failures_preserve_healthy_files_and_exports(self):
        cipher = self.export()
        healthy = self.restores / 'healthy'
        encrypted.restore_export(cipher, healthy, self.identity, self.work)
        exports_before = self.inventories()
        sources_before = {name: path.read_bytes() for name, path in self.sources.items()}
        snapshot_before = {path.name: path.read_bytes() for path in self.snapshot.iterdir()}
        original_write = backup.write_private
        original_rename = os.rename
        for failure in ['write', 'rename']:
            with self.subTest(failure=failure):
                reached = []
                destination = self.restores / ('failed-' + failure)
                def failed_write(path, data, mode=0o600):
                    if failure == 'write' and path.parent.parent.name.startswith('.restore-') and path.name == 'pink-party.env':
                        # The session has already been written after decryption and both validator calls.
                        self.assertEqual((path.parent.parent / 'data/session.json').read_bytes(), sources_before['data/session.json'])
                        original_write(path, data[:8], mode)
                        reached.append('partial restored file written')
                        raise OSError('synthetic disk write failure')
                    return original_write(path, data, mode)
                def failed_rename(source, target):
                    if failure == 'rename' and Path(target) == destination:
                        for name, expected in sources_before.items():
                            self.assertEqual((Path(source) / name).read_bytes(), expected)
                        reached.append('complete validated restore ready for publication')
                        raise OSError('synthetic publication failure')
                    return original_rename(source, target)
                with patch.object(backup, 'write_private', side_effect=failed_write), patch.object(backup.os, 'rename', side_effect=failed_rename):
                    with self.assertRaisesRegex(OSError, 'synthetic'):
                        encrypted.restore_export(cipher, destination, self.identity, self.work)
                self.assertEqual(len(reached), 1)
                self.assertFalse(destination.exists())
                self.assertEqual(list(self.restores.glob('.restore-*')), [])
                self.assertEqual(list(self.work.glob('.decrypt-*')), [])
                self.assertEqual(self.inventories(), exports_before)
                self.assertEqual({path.name: path.read_bytes() for path in self.snapshot.iterdir()}, snapshot_before)
                for name, source in self.sources.items():
                    self.assertEqual(source.read_bytes(), sources_before[name])
                    self.assertEqual((healthy / name).read_bytes(), sources_before[name])
                    self.assertEqual((healthy / name).stat().st_mode & 0o777, backup.MODES[name])

    def test_retention_clock_rollback_and_failed_source_keep_good_exports(self):
        for _ in range(encrypted.KEEP + 1):
            self.export()
        self.assertEqual(len(list(self.exports.glob('export-*'))), encrypted.KEEP)
        before = self.inventories()
        self.snapshot.chmod(0o755)
        with self.assertRaises(ValueError):
            self.export()
        self.snapshot.chmod(0o700)
        self.assertEqual(self.inventories(), before)
        class Earlier(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2020, 1, 1, tzinfo=tz)
        with patch.object(encrypted.dt, 'datetime', Earlier):
            cipher = self.export()
        self.assertTrue(cipher.exists())
        self.assertEqual(len(list(self.exports.glob('export-*'))), encrypted.KEEP)

    def test_source_export_and_restore_overlap_rejected(self):
        with backup.locked(self.store):
            with self.assertRaisesRegex(ValueError, 'Another backup'):
                self.export()
        with backup.locked(self.exports):
            with self.assertRaisesRegex(ValueError, 'Another backup'):
                self.export()
        cipher = self.export()
        for directory in [self.work, self.restores]:
            with backup.locked(directory):
                with self.assertRaisesRegex(ValueError, 'Another backup'):
                    encrypted.restore_export(cipher, self.restores / 'busy', self.identity, self.work)
        self.assertFalse((self.restores / 'busy').exists())

    def test_actual_age_process_timeout_and_output_limit_leave_no_export(self):
        self.export()
        before = self.inventories()
        helper = self.root / 'fake-age'
        helper.write_text('#!/usr/bin/env python3\nimport sys,time\nsys.stdout.write("partial plaintext")\nsys.stdout.flush()\ntime.sleep(10)\n')
        helper.chmod(0o700)
        find_tool = shutil.which
        with patch.object(encrypted.shutil, 'which', side_effect=lambda name: str(helper) if name == 'age' else find_tool(name)), patch.object(encrypted, 'AGE_TIMEOUT', 0.05):
            with self.assertRaises(subprocess.TimeoutExpired):
                self.export()
        self.assertEqual(self.inventories(), before)
        self.assertEqual(list(self.exports.glob('.pending-export-*')), [])
        helper.write_text('#!/usr/bin/env python3\nimport sys\nsys.stdout.buffer.write(b"x"*200000)\nsys.stdout.flush()\n')
        with patch.object(encrypted.shutil, 'which', return_value=str(helper)):
            with self.assertRaisesRegex(ValueError, 'age operation failed'):
                encrypted.age_transform(b'synthetic', [], self.work, 1024)

    def test_unsafe_key_and_ciphertext_paths_rejected(self):
        cipher = self.export()
        self.identity.chmod(0o644)
        with self.assertRaises(ValueError):
            encrypted.verify_export(cipher, self.identity, self.work)
        self.identity.chmod(0o600)
        linked = self.keys / 'linked'
        linked.symlink_to(self.identity)
        with self.assertRaises(OSError):
            encrypted.verify_export(cipher, linked, self.work)
        self.recipient.write_text('age-plugin-malicious-recipient\n')
        with self.assertRaises(ValueError):
            self.export()
        cipher.chmod(0o644)
        with self.assertRaises(ValueError):
            encrypted.verify_export(cipher, self.identity, self.work)


if __name__ == '__main__':
    unittest.main()

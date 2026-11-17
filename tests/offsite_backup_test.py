import datetime as dt
from pathlib import Path
import sys
import subprocess
import unittest
from unittest.mock import patch

import scheduled_recovery_test as local

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'deploy/recovery'))
import offsite

SERVER = next((str(p) for p in [Path('/usr/libexec/sftp-server'), Path('/usr/lib/openssh/sftp-server')]
               if p.is_file()), None)


@unittest.skipUnless(SERVER and local.fixture.shutil.which('age'), 'OpenSSH SFTP server and age required')
class OffsiteBackupTest(unittest.TestCase):
    def setUp(self):
        self.local = local.ScheduledRecoveryTest()
        self.addCleanup(self.local.doCleanups)
        self.local.setUp()
        self.local.collect()
        self.root = self.local.root
        self.collection = self.root / 'collection.json'
        local.f.atomic_json(self.collection, {**self.local.config, 'version': 1,
                            **{k: str(self.local.config[k]) for k in ['store', 'state', 'identity']}})
        self.state = self.root / 'offsite-state'
        self.state.mkdir(mode=0o700)
        self.directory = self.root / 'remote'
        self.directory.mkdir(mode=0o700)
        self.config = dict(collectionConfig=self.collection, state=self.state, destinationBinding='fixture')
        self.remote = offsite.Sftp({'directory': str(self.directory)},
                                  ['/usr/bin/sftp', '-b', '-', '-D', SERVER])
        offsite.initialize_remote(self.remote, self.local.work)

    def run_job(self):
        return local.f.run_job(self.state, lambda previous: offsite.transfer(self.config, previous, self.remote))

    def new_capture(self):
        field = self.local.sources['data/session.json']
        field.write_text(field.read_text().replace('Synthetic game', 'Batch 11 synthetic game'))
        self.local.snapshot = local.b.create_backup(self.local.sources, self.local.store)[0]
        _, manifest = local.b.validate_backup(self.local.snapshot)
        archive = (self.local.snapshot / 'snapshot.tar').read_bytes()
        local.f.run_job(self.local.bs, lambda _: (dict(capturedAt=manifest['capturedAt'],
                        archiveDigest=local.b.digest(archive)), 'captured'))
        self.local.run_export()
        self.local.collect()

    def test_sftp_retrieval_is_idempotent_and_restores_without_source(self):
        first = self.run_job()['success']
        again = self.run_job()['success']
        for key in ['object', 'transferredAt', 'capturedAt']:
            self.assertEqual(first[key], again[key])
        self.assertGreater(again['authenticatedAt'], first['authenticatedAt'])
        self.assertTrue(offsite.inspect(self.config)['healthy'])
        self.local.rolling.rename(self.root / 'unavailable')
        self.collection.unlink()
        (self.directory / offsite.MARKER).unlink()
        result = self.local.restores / 'from-sftp.age'
        offsite.retrieve(self.remote, first['object'], self.local.identity, result)
        restored = self.local.restores / 'restored'
        offsite.encrypted.restore_export(result, restored, self.local.identity, self.local.work)
        for name, path in self.local.sources.items():
            self.assertEqual((restored / name).read_bytes(), path.read_bytes())
            self.assertEqual((restored / name).stat().st_mode & 0o777, offsite.backup.MODES[name])

    def test_interrupted_publication_is_reauthenticated_without_duplicate(self):
        execute = self.remote.execute

        def interrupted(work, commands):
            result = execute(work, commands)
            if commands[0].startswith('@rename'):
                raise offsite.Fault('injected-lost-rename-response')
            return result

        with patch.object(self.remote, 'execute', side_effect=interrupted), self.assertRaises(offsite.Fault):
            self.run_job()
        self.assertFalse(offsite.inspect(self.config)['healthy'])
        self.assertEqual(len(list(self.directory.glob('*.age'))), 1)
        result = self.run_job()['success']
        self.assertIsNone(result['transferredAt'])
        self.assertEqual(len(list(self.directory.glob('*.age'))), 1)
        self.assertTrue(offsite.inspect(self.config)['healthy'])

    def test_missing_changed_unavailable_and_wrong_key_preserve_last_success(self):
        good = self.run_job()['success']
        path = self.directory / good['object']
        original = path.read_bytes()
        for replacement in [None, original[:-9], original[:-9] + b'x' * 9]:
            with self.subTest(replacement='missing' if replacement is None else len(replacement)):
                path.unlink()
                if replacement is not None:
                    local.b.write_private(path, replacement)
                with self.assertRaisesRegex(offsite.Fault, 'remote-copy-(changed|missing)'):
                    self.run_job()
                self.assertFalse(offsite.inspect(self.config)['healthy'])
                self.assertEqual(local.f.read_state(self.state)['success'], good)
                if path.exists():
                    path.unlink()
                local.b.write_private(path, original)
        unavailable = self.root / 'unavailable-remote'
        self.directory.rename(unavailable)
        with self.assertRaises(offsite.Fault):
            self.run_job()
        unavailable.rename(self.directory)
        self.assertFalse(offsite.inspect(self.config)['healthy'])
        result = self.local.restores / 'wrong.age'
        with self.assertRaises(offsite.Fault):
            offsite.retrieve(self.remote, good['object'], self.root / 'unavailable-key', result)
        self.assertFalse(result.exists())
        self.assertEqual(path.read_bytes(), original)
        self.run_job()
        self.assertTrue(offsite.inspect(self.config)['healthy'])

    def test_independent_retrieval_rejects_wrong_key_and_truncated_ciphertext(self):
        success = self.run_job()['success']
        output = self.local.restores / 'candidate.age'
        wrong = self.local.keys / 'wrong'
        subprocess.run(['age-keygen', '-o', str(wrong)], check=True, capture_output=True)
        wrong.chmod(0o600)
        with self.assertRaisesRegex(offsite.Fault, 'authentication-or-validation-failed'):
            offsite.retrieve(self.remote, success['object'], wrong, output)
        self.assertFalse(output.exists())
        original = self.directory / success['object']
        original.write_bytes(original.read_bytes()[:-9])
        with self.assertRaisesRegex(offsite.Fault, 'authentication-or-validation-failed'):
            offsite.retrieve(self.remote, success['object'], self.local.identity, output)
        self.assertFalse(output.exists())

    def test_rotation_only_after_verified_replacement_and_store_full_fails_closed(self):
        first = self.run_job()['success']
        for i in range(7):
            name = f"capture-20200101T00000{i}000000Z-{'a' * 64}.age"
            local.b.write_private(self.directory / name, b'capacity fixture')
        self.new_capture()
        with self.assertRaisesRegex(offsite.Fault, 'remote-store-full'):
            self.run_job()
        self.assertEqual(len(list(self.directory.glob('*.age'))), 8)
        fixture = min(self.directory.glob('*.age'))
        fixture.unlink()
        execute = self.remote.execute

        def partial(work, commands):
            if commands[0].startswith('@put'):
                (self.directory / offsite.PENDING).write_bytes(b'partial fixture')
                (self.directory / offsite.PENDING).chmod(0o600)
                raise offsite.Fault('injected-transfer-interruption')
            return execute(work, commands)

        for reason in ['destination-access-denied', 'destination-quota']:
            with patch.object(self.remote, 'execute', side_effect=offsite.Fault(reason)):
                with self.assertRaisesRegex(offsite.Fault, reason):
                    self.run_job()
            self.assertEqual(local.f.read_state(self.state)['success'], first)
        with patch.object(self.remote, 'execute', side_effect=partial), self.assertRaises(offsite.Fault):
            self.run_job()
        self.assertEqual(len(list(self.directory.glob('*.age'))), 7)
        self.assertTrue((self.directory / first['object']).exists())
        new = self.run_job()['success']
        self.assertNotEqual(first['object'], new['object'])
        self.assertEqual(len(list(self.directory.glob('*.age'))), 7)
        self.assertTrue((self.directory / first['object']).exists())

    def test_stale_clock_rollback_corrupt_state_and_overlap_fail_closed(self):
        self.run_job()
        end = local.f.instant(local.f.now())
        for delta in [-1, offsite.CAPTURE_MAX + 1]:
            with patch.object(offsite, 'now', return_value=(end + dt.timedelta(seconds=delta)).isoformat()):
                self.assertFalse(offsite.inspect(self.config)['healthy'])
        self.assertFalse(offsite.inspect({**self.config, 'destinationBinding': 'other'})['healthy'])
        saved = local.f.read_state(self.state)
        spliced = {**saved, 'attemptedAt': local.f.now(), 'finishedAt': local.f.now()}
        local.f.atomic_json(self.state / 'status.json', spliced)
        self.assertFalse(offsite.inspect(self.config)['healthy'])
        local.f.atomic_json(self.state / 'status.json', saved)
        with local.b.locked(self.state), self.assertRaisesRegex(ValueError, 'Another backup'):
            self.run_job()
        path = self.state / 'status.json'
        path.write_bytes(b'broken\n')
        with self.assertRaisesRegex(offsite.Fault, 'state-invalid'):
            self.run_job()
        self.assertFalse(offsite.inspect(self.config)['healthy'])
        self.assertEqual(path.read_bytes(), b'broken\n')

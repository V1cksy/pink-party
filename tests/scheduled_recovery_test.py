import base64
import datetime as dt
import json
from pathlib import Path
import subprocess
import sys
import os
import signal
import time
import unittest
from unittest.mock import patch

import linux_encrypted_backup_test as fixture

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'deploy/recovery'))
import collector

f = sys.modules['freshness']
b = f.backup
exporter = collector.load('scheduled_export', ROOT / 'deploy/linux/scheduled-export.py')


@unittest.skipUnless(fixture.shutil.which('age'), 'Install age')
class ScheduledRecoveryTest(unittest.TestCase):
    def setUp(self):
        fixture.EncryptedBackupTest.setUp(self)
        self.rolling = self.root / 'rolling'
        self.state = self.root / 'state'
        self.bs = self.root / 'backup-status'
        self.es = self.root / 'export-status'
        self.bs.mkdir(mode=0o700)
        self.es.mkdir(mode=0o700)
        self.config = dict(store=self.rolling, state=self.state, identity=self.identity, vm='synthetic')
        collector.initialize(self.config)
        manifest = b.validate_backup(self.snapshot)[1]
        capture = dict(snapshot=self.snapshot.name, capturedAt=manifest['capturedAt'],
                       archiveDigest=b.digest((self.snapshot / 'snapshot.tar').read_bytes()))
        f.run_job(self.bs, lambda previous: (capture, 'captured'))
        self.run_export()

    def run_export(self):
        return f.run_job(self.es, lambda previous: exporter.export(
            previous, self.store, self.exports, self.recipient, self.bs))

    def offer(self):
        state = f.read_state(self.es)
        data = (self.exports / state['success']['export'] / 'snapshot.tar.age').read_bytes()
        return {'source': dict(observedAt=f.now(), backup=f.read_state(self.bs), export=state),
                'ciphertext': base64.b64encode(data).decode()}

    def collect(self, offer=None):
        transfer = lambda vm, destination: json.dumps(offer or self.offer()).encode()
        return f.run_job(self.state, lambda previous: collector.collect(self.config, previous, transfer))

    def inventory(self):
        return {p.name: p.read_bytes() for p in self.rolling.glob('*.age')}

    def test_scheduled_export_deduplicates_capture_and_collection_authenticates(self):
        before = list(self.exports.glob('export-*'))
        self.assertEqual(self.run_export()['reason'], 'unchanged')
        self.assertEqual(list(self.exports.glob('export-*')), before)
        first = self.collect()['success']
        self.assertTrue(collector.inspect(self.config)['healthy'])
        again = self.collect()['success']
        self.assertEqual(first['collectedAt'], again['collectedAt'])
        self.assertEqual(len(self.inventory()), 1)
        destination = self.restores / 'automated'
        collector.encrypted.restore_export(next(self.rolling.glob('*.age')), destination, self.identity, self.work)
        for name in b.MODES:
            self.assertEqual((destination / name).read_bytes(), self.sources[name].read_bytes())
            self.assertEqual((destination / name).stat().st_mode & 0o777, b.MODES[name])

    def test_failed_export_preserves_last_success_and_ciphertext(self):
        before = {p.name: (p / 'snapshot.tar.age').read_bytes() for p in self.exports.glob('export-*')}
        original = f.read_state(self.es)['success']
        # A new capture is necessary: unchanged captures intentionally avoid encryption.
        self.snapshot = b.create_backup(self.sources, self.store)[0]
        capture = b.validate_backup(self.snapshot)[1]
        f.run_job(self.bs, lambda old: (dict(capturedAt=capture['capturedAt'],
            archiveDigest=b.digest((self.snapshot / 'snapshot.tar').read_bytes())), 'captured'))
        with patch.object(exporter.encrypted, 'age_transform', side_effect=ValueError('injected encryption failure')):
            with self.assertRaises(f.Fault): self.run_export()
        self.assertEqual(f.read_state(self.es)['success'], original)
        self.assertEqual(f.read_state(self.es)['outcome'], 'error')
        self.assertEqual(before, {p.name: (p / 'snapshot.tar.age').read_bytes() for p in self.exports.glob('export-*')})

    def test_missing_and_stale_capture_never_export(self):
        self.snapshot.rename(self.root / 'protected-snapshot')
        with self.assertRaisesRegex(f.Fault, 'missing'): self.run_export()
        (self.root / 'protected-snapshot').rename(self.snapshot)
        future = dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=f.CAPTURE_MAX + 1)
        with patch.object(exporter, 'now', return_value=future.isoformat()):
            with self.assertRaisesRegex(f.Fault, 'stale'): self.run_export()

    def test_wrong_missing_unavailable_key_keeps_good_copy_and_success(self):
        good = self.collect()['success']; before = self.inventory()
        wrong = self.keys / 'wrong'
        subprocess.run(['age-keygen', '-o', str(wrong)], check=True, stderr=subprocess.DEVNULL)
        wrong.chmod(0o600)
        for key in [wrong, self.keys / 'missing']:
            self.config['identity'] = key
            with self.assertRaisesRegex(f.Fault, 'authentication'): self.collect()
            self.assertEqual(f.read_state(self.state)['success'], good)
            self.assertFalse(collector.inspect(self.config)['healthy'])
            self.assertEqual(self.inventory(), before)
        self.config['identity'] = self.identity
        self.identity.chmod(0o000)
        with self.assertRaises(f.Fault): self.collect()
        self.identity.chmod(0o600)
        self.collect()
        self.assertTrue(collector.inspect(self.config)['healthy'])

    def test_corrupt_and_truncated_authenticated_input_never_prunes(self):
        self.collect(); before = self.inventory()
        for mutation in ['corrupt', 'truncated']:
            offer = self.offer(); raw = base64.b64decode(offer['ciphertext'])
            raw = raw[:-1] if mutation == 'truncated' else raw[:-1] + bytes([raw[-1] ^ 1])
            offer['ciphertext'] = base64.b64encode(raw).decode()
            # Even a matching transport hash cannot replace age authentication.
            offer['source']['export']['success']['cipherDigest'] = b.digest(raw)
            with self.assertRaisesRegex(f.Fault, 'authentication'): self.collect(offer)
            self.assertEqual(self.inventory(), before)

    def test_full_store_and_pruning_failure_preserve_prior_copies(self):
        self.collect(); original = self.inventory()
        for i in range(7):
            b.write_private(self.rolling / ('export-20200101T000000000000Z-%08x.age' % i), b'synthetic retained')
        offer = self.offer()
        offer['source']['export']['success']['export'] = 'export-20261117T000000000000Z-abcdefab'
        before = self.inventory()
        with self.assertRaisesRegex(f.Fault, 'store-full'): self.collect(offer)
        self.assertEqual(self.inventory(), before)
        # Seven copies permit a validated eighth, but a failed retirement cannot report success.
        next(p for p in self.rolling.glob('export-2020*')).unlink()
        before = self.inventory()
        unlink = Path.unlink
        def fail_retirement(path, *args, **kwargs):
            if path.parent == self.rolling and path.suffix == '.age': raise OSError('injected retirement failure')
            return unlink(path, *args, **kwargs)
        with patch.object(Path, 'unlink', fail_retirement):
            with self.assertRaises(f.Fault): self.collect(offer)
        for name, data in before.items(): self.assertEqual((self.rolling / name).read_bytes(), data)
        self.assertEqual(len(self.inventory()), 8)
        self.assertEqual(f.read_state(self.state)['outcome'], 'error')
        self.collect(offer)
        self.assertEqual(len(self.inventory()), 7)
        for name, data in original.items(): self.assertEqual((self.rolling / name).read_bytes(), data)

    def test_interrupted_transfer_and_publication_do_not_claim_success(self):
        self.collect(); before = self.inventory()
        def interrupted(vm, destination):
            b.write_private(destination, b'partial response')
            raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt):
            f.run_job(self.state, lambda old: collector.collect(self.config, old, interrupted))
        self.assertEqual(f.read_state(self.state)['outcome'], 'running')
        self.assertFalse(collector.inspect(self.config)['healthy'])
        self.assertEqual(self.inventory(), before)
        offer = self.offer(); offer['source']['export']['success']['export'] = 'export-20261117T000000000000Z-abcdefab'
        with patch.object(collector.os, 'rename', side_effect=OSError('injected publication failure')):
            with self.assertRaises(f.Fault): self.collect(offer)
        self.assertEqual(self.inventory(), before)
        self.assertEqual(list(self.rolling.glob('.collect-*')), [])
        self.collect()

    def test_overlap_source_unavailable_and_recovery(self):
        self.collect(); before = self.inventory()
        with b.locked(self.state):
            with self.assertRaisesRegex(ValueError, 'Another'): self.collect()
        def unavailable(vm, destination): raise subprocess.TimeoutExpired('synthetic transfer', 25)
        with self.assertRaisesRegex(f.Fault, 'source-unavailable'):
            f.run_job(self.state, lambda old: collector.collect(self.config, old, unavailable))
        self.assertFalse(collector.inspect(self.config)['healthy'])
        self.assertEqual(self.inventory(), before)
        self.collect(); self.assertTrue(collector.inspect(self.config)['healthy'])

    def test_corrupt_state_clock_rollback_and_old_capture_fail_closed(self):
        self.collect(); state = f.read_state(self.state)
        (self.state / 'status.json').write_text('{invalid')
        self.assertFalse(collector.inspect(self.config)['healthy'])
        with self.assertRaises(f.Fault): self.collect()
        f.atomic_json(self.state / 'status.json', state)
        earlier = (f.instant(state['attemptedAt']) - dt.timedelta(seconds=1)).isoformat()
        with patch.object(f, 'now', return_value=earlier):
            with self.assertRaisesRegex(f.Fault, 'clock-skew'): self.collect()
        future = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=f.CAPTURE_MAX + 1)).isoformat()
        with patch.object(collector, 'now', return_value=future):
            self.assertFalse(collector.inspect(self.config)['healthy'])

    def test_mutated_or_missing_copy_and_existing_vault_cannot_be_healthy(self):
        self.collect(); cipher = next(self.rolling.glob('*.age')); cipher.write_bytes(b'broken')
        self.assertFalse(collector.inspect(self.config)['healthy'])
        cipher.unlink()
        self.assertFalse(collector.inspect(self.config)['healthy'])
        config = {**self.config, 'store': self.exports}
        with self.assertRaises(FileExistsError): collector.initialize(config)

    def test_cached_source_observation_remains_fresh_between_normal_ticks(self):
        self.collect()
        at = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=45)).isoformat()
        with patch.object(collector, 'now', return_value=at):
            self.assertTrue(collector.inspect(self.config)['healthy'])

    def test_worker_cleanup_reaps_descendants_even_after_ordinary_failure(self):
        helper = self.root / 'worker.py'
        pidfile = self.root / 'child-pid'
        helper.write_text('import subprocess,sys\nfrom pathlib import Path\n'
            'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"])\n'
            'Path(sys.argv[1]).write_text(str(p.pid))\nsys.exit(1)\n')
        popen = subprocess.Popen
        def worker(*args, **kwargs):
            return popen([sys.executable, str(helper), str(pidfile)], **kwargs)
        with patch.object(collector.subprocess, 'Popen', side_effect=worker):
            self.assertEqual(collector.bounded_run(self.root / 'unused'), 1)
        pid = int(pidfile.read_text())
        for _ in range(30):
            try:
                result = subprocess.run(['ps', '-p', str(pid), '-o', 'stat='], capture_output=True, timeout=2)
                if result.returncode != 0 or result.stdout.strip().startswith(b'Z'):
                    break
            except ProcessLookupError:
                break
            time.sleep(0.02)
        else:
            os.kill(pid, signal.SIGKILL)
            self.fail('Worker descendant survived cleanup')

    def test_repeated_exercise_begin_does_not_lock_or_pause_schedulers(self):
        exercise = collector.load('scheduled_exercise', ROOT / 'deploy/linux/exercise-scheduled.py')
        exercise.WORK = self.root / 'already-completed'
        exercise.WORK.mkdir(mode=0o700)
        exercise.LOCK = self.root / 'verification-lock'
        with patch.object(exercise, 'ctl') as ctl:
            with self.assertRaises(f.Fault): exercise.begin()
            ctl.assert_not_called()
        self.assertFalse(exercise.LOCK.exists())

    def test_changed_exercise_data_always_has_a_recoverable_journal(self):
        exercise = collector.load('scheduled_exercise', ROOT / 'deploy/linux/exercise-scheduled.py')
        exercise.WORK = self.root / 'exercise'
        exercise.LOCK = self.root / 'verification-lock'
        original = self.sources['data/session.json'].read_bytes()
        def ctl(*args):
            if args[0] == 'restart': raise RuntimeError('injected restart failure')
        with patch.object(exercise, 'healthy', return_value=True), patch.object(exercise, 'ctl', side_effect=ctl), patch.object(exercise.backup, 'SOURCES', self.sources):
            with self.assertRaisesRegex(RuntimeError, 'injected'): exercise.begin()
        self.assertNotEqual(self.sources['data/session.json'].read_bytes(), original)
        self.assertEqual((exercise.WORK / 'original-session.json').read_bytes(), original)
        self.assertIn('startedAt', f.read_json(exercise.WORK / 'report.json'))

    def test_repeated_fault_initialization_leaves_schedulers_untouched(self):
        exercise = collector.load('export_exercise', ROOT / 'deploy/linux/exercise-export-failures.py')
        workspace = self.restores / 'existing'
        workspace.mkdir(mode=0o700)
        with patch.object(exercise.backup, 'RESTORES', self.restores), patch.object(exercise.os, 'geteuid', return_value=0), patch.object(exercise, 'pause') as pause, patch.object(sys, 'argv', ['exercise', 'initialize', '--work-name', 'existing']):
            with self.assertRaises(f.Fault): exercise.main()
            pause.assert_not_called()

    def test_missing_or_corrupt_fault_checkpoint_cannot_delete_live_backups(self):
        exercise = collector.load('export_exercise', ROOT / 'deploy/linux/exercise-export-failures.py')
        before = {p.name: p.read_bytes() for p in self.snapshot.iterdir()}
        for workspace in [self.restores / 'missing', self.restores / 'corrupt']:
            if workspace.name == 'corrupt':
                workspace.mkdir(mode=0o700)
                (workspace / 'backups').mkdir(mode=0o700)
            for case in ['restore', 'missing', 'stale', 'failed-export', 'corrupt', 'truncated']:
                with self.subTest(workspace=workspace.name, case=case), patch.object(exercise.backup, 'RESTORES', self.restores), patch.object(exercise.backup, 'STORE', self.store), patch.object(exercise.os, 'geteuid', return_value=0), patch.object(exercise, 'pause') as pause, patch.object(sys, 'argv', ['exercise', case, '--work-name', workspace.name]):
                    with self.assertRaises((OSError, ValueError)): exercise.main()
                    pause.assert_not_called()
                    self.assertEqual(before, {p.name: p.read_bytes() for p in self.snapshot.iterdir()})

    def test_publication_interruptions_preserve_good_copies_and_require_revalidation(self):
        previous = self.collect()['success']
        before = self.inventory()
        offer = self.offer()
        name = 'export-20261117T000000000000Z-abcdefab'
        offer['source']['export']['success']['export'] = name
        with patch.object(collector.os, 'rename', side_effect=KeyboardInterrupt()):
            with self.assertRaises(KeyboardInterrupt): self.collect(offer)
        self.assertEqual(self.inventory(), before)
        sync = collector.backup.sync_directory
        def interrupted_sync(path):
            if path == self.rolling: raise KeyboardInterrupt()
            return sync(path)
        with patch.object(collector.backup, 'sync_directory', side_effect=interrupted_sync):
            with self.assertRaises(KeyboardInterrupt): self.collect(offer)
        self.assertTrue((self.rolling / (name + '.age')).exists())
        self.assertEqual(f.read_state(self.state)['success'], previous)
        self.assertFalse(collector.inspect(self.config)['healthy'])
        for filename, data in before.items(): self.assertEqual((self.rolling / filename).read_bytes(), data)
        self.collect(offer)
        self.assertTrue(collector.inspect(self.config)['healthy'])
        self.assertEqual(len(self.inventory()), len(before) + 1)

    def test_corrupt_failure_reason_cannot_turn_an_error_into_healthy_status(self):
        self.collect()
        state = f.read_state(self.state)
        state.update(outcome='error', reason='fresh-authenticated-copy')
        f.atomic_json(self.state / 'status.json', state)
        self.assertFalse(collector.inspect(self.config)['healthy'])
        self.assertTrue(collector.inspect(self.config)['reason'].startswith('job-error:'))


if __name__ == '__main__': unittest.main()

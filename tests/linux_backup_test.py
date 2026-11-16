import datetime as dt
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tarfile
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('backup', Path(__file__).resolve().parents[1] / 'deploy/linux/backup.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)


class BackupTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.store = self.root / 'backups'
        self.restores = self.root / 'restores'
        self.store.mkdir(mode=0o700)
        self.restores.mkdir(mode=0o700)
        self.sources = {name: self.root / name.replace('/', '-') for name in backup.MODES}
        self.sources['data/session.json'].write_text(json.dumps({'synthetic': True, 'title': 'Synthetic A', 'game': 'Synthetic game', 'description': 'A synthetic session.', 'startsAt': '2026-11-16T20:00:00+01:00', 'timeZone': 'Europe/Madrid', 'tag': 'Lab'}))
        self.sources['private/pink-party.env'].write_text('PINK_PARTY_MODE=local\nJOIN_CODE=' + 'j' * 24 + '\nLIVEKIT_API_KEY=' + 'k' * 24 + '\nLIVEKIT_API_SECRET=' + 's' * 64 + '\n')
        for name, path in self.sources.items():
            path.chmod(backup.MODES[name])

    def create(self):
        return backup.create_backup(self.sources, self.store)[0]

    def rewrite(self, directory, transform):
        raw = (directory / 'snapshot.tar').read_bytes()
        output = io.BytesIO()
        with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as src, tarfile.open(fileobj=output, mode='w', format=tarfile.USTAR_FORMAT) as dest:
            for member in src:
                data = src.extractfile(member).read()
                member, data = transform(member, data)
                member.size = len(data)
                dest.addfile(member, io.BytesIO(data))
        (directory / 'snapshot.tar').write_bytes(output.getvalue())
        (directory / 'sha256').write_text(hashlib.sha256(output.getvalue()).hexdigest() + '\n')

    def test_roundtrip_exact_bytes_modes_and_no_overwrite(self):
        directory = self.create()
        destination = self.restores / 'one'
        backup.restore_backup(directory, destination)
        for name, source in self.sources.items():
            self.assertEqual((destination / name).read_bytes(), source.read_bytes())
            self.assertEqual((destination / name).stat().st_mode & 0o777, backup.MODES[name])
            self.assertEqual((destination / name).stat().st_uid, os.geteuid())
            self.assertEqual((destination / name).parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(destination.stat().st_mode & 0o777, 0o700)
        with self.assertRaisesRegex(ValueError, 'already exists'):
            backup.restore_backup(directory, destination)
        self.assertEqual((directory / 'snapshot.tar').stat().st_mode & 0o777, 0o600)

    def test_checksum_and_payload_corruption_rejected_before_writes(self):
        directory = self.create()
        archive = directory / 'snapshot.tar'
        original = archive.read_bytes()
        archive.write_bytes(original[:-1])
        with self.assertRaisesRegex(ValueError, 'checksum'):
            backup.restore_backup(directory, self.restores / 'bad')
        self.assertFalse((self.restores / 'bad').exists())
        archive.write_bytes(original)
        self.rewrite(directory, lambda member, data: (member, data.replace(b'Synthetic A', b'Synthetic B')))
        with self.assertRaisesRegex(ValueError, 'integrity'):
            backup.restore_backup(directory, self.restores / 'bad')
        self.assertEqual(list(self.restores.iterdir()), [])

    def test_archive_paths_links_duplicates_and_modes_rejected(self):
        for mutation in ['../escape', '/absolute', 'data/../../escape', 'link', 'duplicate', 'mode', 'device', 'extra']:
            with self.subTest(mutation=mutation):
                directory = self.create()
                def change(member, data):
                    if member.name == 'data/session.json':
                        if mutation == 'link':
                            member.type, member.linkname = tarfile.SYMTYPE, '/etc/passwd'
                        elif mutation == 'device':
                            member.type = tarfile.CHRTYPE
                        elif mutation == 'mode':
                            member.mode = 0o777
                        else:
                            member.name = 'private/pink-party.env' if mutation == 'duplicate' else mutation
                    return member, data
                self.rewrite(directory, change)
                with self.assertRaises(ValueError):
                    backup.restore_backup(directory, self.restores / 'bad')
                self.assertFalse((self.restores / 'bad').exists())
                self.assertFalse((self.root / 'escape').exists())

    def test_failure_never_prunes_and_retention_is_bounded(self):
        for _ in range(backup.KEEP + 2):
            self.create()
        before = {p.name: (p / 'snapshot.tar').read_bytes() for p in self.store.iterdir() if p.is_dir()}
        self.assertEqual(len(before), backup.KEEP)
        self.sources['private/pink-party.env'].chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'permission'):
            self.create()
        self.assertEqual(before, {p.name: (p / 'snapshot.tar').read_bytes() for p in self.store.iterdir() if p.is_dir()})
        self.sources['private/pink-party.env'].chmod(0o600)
        with patch.object(backup, 'validate_backup', side_effect=ValueError('validation fault')):
            with self.assertRaisesRegex(ValueError, 'validation fault'):
                self.create()
        self.assertEqual(before, {p.name: (p / 'snapshot.tar').read_bytes() for p in self.store.iterdir() if p.is_dir()})
        self.assertEqual(list(self.store.glob('.pending-*')), [])

    def test_clock_rollback_retains_newly_published_backup(self):
        for _ in range(backup.KEEP):
            self.create()
        class Earlier(dt.datetime):
            @classmethod
            def now(cls, tz=None):
                return cls(2020, 1, 1, tzinfo=tz)
        with patch.object(backup.dt, 'datetime', Earlier):
            target = self.create()
        self.assertTrue(target.exists())
        self.assertEqual(len(list(self.store.glob('backup-*'))), backup.KEEP)

    def test_application_schema_rejects_invalid_session(self):
        directory = self.create()
        self.sources['data/session.json'].write_text('{"synthetic": true}')
        with self.assertRaisesRegex(ValueError, 'Application session validation'):
            self.create()
        self.assertTrue(directory.exists())
        self.assertEqual(len(list(self.store.glob('backup-*'))), 1)

    def test_unsafe_files_directories_and_overlap_rejected(self):
        directory = self.create()
        with backup.locked(self.store):
            with self.assertRaisesRegex(ValueError, 'Another backup'):
                self.create()
            with self.assertRaisesRegex(ValueError, 'Another backup'):
                backup.restore_backup(directory, self.restores / 'busy')
        self.sources['data/session.json'].unlink()
        self.sources['data/session.json'].symlink_to(self.sources['private/pink-party.env'])
        with self.assertRaises(OSError):
            self.create()
        self.store.chmod(0o755)
        with self.assertRaisesRegex(ValueError, '0700'):
            self.create()
        self.store.chmod(0o700)
        with self.assertRaises(FileNotFoundError):
            backup.restore_backup(self.store / 'missing', self.restores / 'missing')
        self.assertFalse((self.restores / 'missing').exists())
        linked = self.restores / 'linked'
        linked.symlink_to(self.root / 'absent')
        with self.assertRaisesRegex(ValueError, 'already exists'):
            backup.restore_backup(directory, linked)

    def test_interrupted_stage_cleaned_and_changed_source_not_published(self):
        stage = self.store / '.pending-interrupted'
        stage.mkdir(mode=0o700)
        (stage / 'partial').write_text('synthetic partial')
        self.create()
        self.assertFalse(stage.exists())
        original = backup.validate_backup
        def changed(directory):
            result = original(directory)
            self.sources['data/session.json'].write_text('{"synthetic": true, "title": "Changed"}')
            return result
        before = set(self.store.iterdir())
        with patch.object(backup, 'validate_backup', side_effect=changed):
            with self.assertRaisesRegex(ValueError, 'Source changed'):
                self.create()
        self.assertEqual(set(self.store.iterdir()), before)


if __name__ == '__main__':
    unittest.main()

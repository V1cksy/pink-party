import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

LINUX = Path(__file__).resolve().parents[1] / 'deploy/linux'
sys.path.insert(0, str(LINUX))
spec = importlib.util.spec_from_file_location('recovery_config', LINUX / 'recovery-config.py')
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class RecoveryConfigTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.root.chmod(0o700)
        self.source = self.root / 'recovered'
        self.source.mkdir(mode=0o700)
        for folder in ['data', 'private']:
            (self.source / folder).mkdir(mode=0o700)
        session = {'synthetic': True, 'title': 'Recovered synthetic evening',
                   'game': 'Synthetic game', 'description': 'Recovery fixture.',
                   'startsAt': '2026-11-17T20:00:00+01:00',
                   'timeZone': 'Europe/Madrid', 'tag': 'Recovery lab'}
        (self.source / 'data/session.json').write_text(json.dumps(session))
        (self.source / 'data/session.json').chmod(0o644)
        (self.source / 'private/pink-party.env').write_text(
            'PINK_PARTY_MODE=local\nJOIN_CODE=' + 'j' * 24
            + '\nLIVEKIT_API_KEY=' + 'k' * 24 + '\nLIVEKIT_API_SECRET=' + 's' * 64 + '\n')
        (self.source / 'private/pink-party.env').chmod(0o600)

    def test_stage_preserves_recovered_bytes_and_modes_without_replacing_inputs(self):
        destination = self.root / 'staged'
        original = recovery.recovered_payloads(self.source)
        recovery.stage_recovery(self.source, destination)
        self.assertEqual(recovery.recovered_payloads(destination), original)
        self.assertEqual(recovery.recovered_payloads(self.source), original)
        self.assertEqual(destination.stat().st_uid, os.geteuid())
        self.assertEqual(destination.stat().st_mode & 0o777, 0o700)
        with self.assertRaisesRegex(ValueError, 'already exists'):
            recovery.stage_recovery(self.source, destination)
        self.assertEqual(recovery.recovered_payloads(destination), original)

    def test_fresh_guest_check_rejects_every_installed_path_and_dangling_link(self):
        paths = recovery.FRESH_PATHS + ['etc/systemd/system/' + unit for unit in recovery.UNITS]
        recovery.require_fresh(self.root)
        for relative in paths:
            with self.subTest(path=relative):
                target = self.root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.symlink_to(self.root / 'missing')
                with self.assertRaisesRegex(ValueError, 'fresh guest'):
                    recovery.require_fresh(self.root)
                target.unlink()

    def test_fresh_guest_rejects_a_symlinked_installation_parent(self):
        (self.root / 'elsewhere').mkdir()
        (self.root / 'opt').symlink_to(self.root / 'elsewhere')
        with self.assertRaisesRegex(ValueError, 'ancestors'):
            recovery.require_fresh(self.root)

    def test_private_configuration_is_rejected_before_staging(self):
        (self.source / 'private/pink-party.env').write_text(
            'PINK_PARTY_MODE=private\nPUBLIC_ORIGIN=https://cloud.example-tail.ts.net\n'
            'TAILSCALE_IP=100.100.100.100\nINVITED_LOGINS=peach@example.com\n'
            'LIVEKIT_API_KEY=' + 'k' * 24 + '\nLIVEKIT_API_SECRET=' + 's' * 64 + '\n')
        destination = self.root / 'staged'
        with self.assertRaisesRegex(ValueError, 'local mode only'):
            recovery.stage_recovery(self.source, destination)
        self.assertFalse(destination.exists())

    def test_invalid_schema_modes_and_unexpected_files_publish_nothing(self):
        destination = self.root / 'staged'
        original = (self.source / 'data/session.json').read_bytes()
        (self.source / 'data/session.json').write_text('{"synthetic":true}')
        with self.assertRaisesRegex(ValueError, 'session validation'):
            recovery.stage_recovery(self.source, destination)
        self.assertFalse(destination.exists())
        (self.source / 'data/session.json').write_bytes(original)
        (self.source / 'private/pink-party.env').chmod(0o644)
        with self.assertRaisesRegex(ValueError, 'permission'):
            recovery.stage_recovery(self.source, destination)
        (self.source / 'private/pink-party.env').chmod(0o600)
        (self.source / 'extra').write_text('synthetic unexpected input')
        with self.assertRaisesRegex(ValueError, 'Unexpected recovery files'):
            recovery.stage_recovery(self.source, destination)
        self.assertFalse(destination.exists())

    def test_interrupted_staging_never_leaves_a_publishable_destination(self):
        destination = self.root / 'staged'
        original = recovery.recovered_payloads(self.source)
        with patch.object(recovery, 'write_private', side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                recovery.stage_recovery(self.source, destination)
        self.assertFalse(destination.exists())
        self.assertEqual(recovery.recovered_payloads(self.source), original)


if __name__ == '__main__':
    unittest.main()

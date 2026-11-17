import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts/ci-linux.sh'


class CiGuardTest(unittest.TestCase):
    def test_personal_checkout_cannot_run_ci_cleanup(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / '.env').write_text('PRIVATE_SENTINEL=keep\n')
            (root / '.local').mkdir()
            (root / '.local/sentinel').write_text('keep')
            result = subprocess.run(['bash', str(SCRIPT)], cwd=root,
                                    env={'PATH': os.defpath}, capture_output=True, timeout=5)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(b'disposable Linux ARM64', result.stderr)
            self.assertEqual((root / '.env').read_text(), 'PRIVATE_SENTINEL=keep\n')
            self.assertEqual((root / '.local/sentinel').read_text(), 'keep')

    def test_runner_checkout_with_existing_configuration_or_state_is_preserved(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            binary = root / 'bin'
            binary.mkdir()
            uname = binary / 'uname'
            uname.write_text('#!/bin/sh\ncase "$1" in -s) echo Linux;; -m) echo aarch64;; esac\n')
            uname.chmod(0o700)
            env = {'PATH': str(binary) + ':' + os.defpath, 'GITHUB_ACTIONS': 'true',
                   'RUNNER_OS': 'Linux', 'RUNNER_ARCH': 'ARM64',
                   'GITHUB_WORKSPACE': str(root), 'RUNNER_TEMP': str(root)}
            for name in ['.env', '.local']:
                for symlink in [False, True]:
                    with self.subTest(name=name, symlink=symlink):
                        sentinel = root / 'sentinel'
                        sentinel.write_text('keep')
                        target = root / name
                        if symlink:
                            target.symlink_to(sentinel)
                        else:
                            target.write_text('keep')
                        result = subprocess.run(['bash', str(SCRIPT)], cwd=root, env=env,
                                                capture_output=True, timeout=5)
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn(b'fresh checkout', result.stderr)
                        self.assertEqual(target.read_text(), 'keep')
                        self.assertEqual(sentinel.read_text(), 'keep')
                        self.assertFalse(list(root.glob('pink-party-ci.*')))
                        target.unlink()


if __name__ == '__main__':
    unittest.main()

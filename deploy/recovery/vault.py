#!/usr/bin/env python3
"""Collect only encrypted exports from a Linux guest into a private Mac vault."""

import argparse
import importlib.util
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time

spec = importlib.util.spec_from_file_location('backup', Path(__file__).resolve().parents[1] / 'linux/backup.py')
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)
LIMIT = 131072
KEEP = 7


def collect(vm, export, vault):
    backup.require(re.fullmatch(r'[a-zA-Z0-9_-]{1,64}', vm), 'Invalid VM name')
    backup.require(re.fullmatch(r'export-[a-zA-Z0-9_-]{1,80}', export), 'Invalid export name')
    backup.private_directory(vault)
    # Read only the fixed encrypted filename. Never stream plaintext or a guest environment.
    with backup.locked(vault):
        for stale in vault.glob('.collect-*'):
            backup.private_directory(stale)
            shutil.rmtree(stale)
        completed = [path for path in vault.iterdir() if re.fullmatch(r'export-[a-zA-Z0-9_-]{1,80}\.age', path.name)]
        # Manual retirement protects recovery material until an operator has tested a replacement.
        backup.require(len(completed) < KEEP, 'Vault is full; verify retained recovery material before manual retirement')
        destination = vault / (export + '.age')
        backup.require(not destination.exists(), 'Vault destination already exists')
        with tempfile.TemporaryDirectory(prefix='.collect-', dir=vault) as temporary:
            stage = Path(temporary) / 'snapshot.age'
            with open(stage, 'xb') as stream:
                os.fchmod(stream.fileno(), 0o600)
                # head bounds transferred/output bytes even if the guest input is faulty.
                result = subprocess.run(['limactl', 'shell', '--workdir=/tmp', vm, 'sudo',
                                         'head', '-c', str(LIMIT + 1),
                                         '/var/lib/pink-party-exports/' + export + '/snapshot.tar.age'],
                                        stdout=stream, stderr=subprocess.DEVNULL, timeout=30)
                stream.flush()
                os.fsync(stream.fileno())
            backup.require(result.returncode == 0, 'Encrypted transfer failed')
            data = backup.read_regular(stage, LIMIT, 0o600)
            backup.require(data.startswith(b'age-encryption.org/v1\n'), 'Invalid encrypted export header')
            # Authentication is a separate verify step using the separately retained key.
            os.link(stage, destination)
            stage.unlink()
            backup.sync_directory(vault)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('vm')
    parser.add_argument('export')
    parser.add_argument('vault', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    start = time.monotonic()
    collect(args.vm, args.export, args.vault)
    print('Encrypted copy collected atomically; authenticate and validate before recovery. '
          + str(round((time.monotonic() - start) * 1000)) + ' ms.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, subprocess.SubprocessError):
        print('Vault collection failed; check private directory, VM, export and destination.', file=sys.stderr)
        sys.exit(1)

#!/usr/bin/env python3
"""Encrypt a validated Linux snapshot, or validate and restore an age export."""

import argparse
import contextlib
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import re
import resource
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import uuid

spec = importlib.util.spec_from_file_location('linux_backup', Path(__file__).with_name('backup.py'))
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)

CIPHER_LIMIT = 131072
AGE_TIMEOUT = 15
KEEP = 7
EXPORT_NAME = re.compile(r'export-\d{8}T\d{12}Z-[a-f0-9]{8}')


def read_recipient(path):
    backup.private_directory(path.parent)
    value = backup.read_regular(path, 128, 0o600).decode('ascii').strip()
    backup.require(re.fullmatch(r'age1[0-9a-z]{58}', value), 'Use one native age X25519 recipient')
    return value


def read_identity(path):
    backup.private_directory(path.parent)
    data = backup.read_regular(path, 1024, 0o600)
    lines = [line for line in data.decode('ascii').splitlines() if line and not line.startswith('#')]
    backup.require(len(lines) == 1 and re.fullmatch(r'AGE-SECRET-KEY-1[0-9A-Z]{58}', lines[0]),
                   'Use one native age X25519 identity')
    return (lines[0] + '\n').encode('ascii')


def age_transform(data, arguments, directory, limit):
    executable = shutil.which('age')
    backup.require(executable is not None, 'Install age before export or recovery')

    def bound_output():
        resource.setrlimit(resource.RLIMIT_FSIZE, (limit, limit))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))

    # Read stdout only after age exits successfully: streaming plaintext is not authenticated yet.
    with tempfile.TemporaryFile(dir=directory) as output:
        result = subprocess.run([executable, *arguments], input=data, stdout=output,
                                stderr=subprocess.DEVNULL, timeout=AGE_TIMEOUT,
                                preexec_fn=bound_output, env={'PATH': os.defpath})
        backup.require(result.returncode == 0, 'age operation failed; check key and encrypted input')
        output.seek(0)
        value = output.read(limit + 1)
        backup.require(0 < len(value) <= limit, 'age output exceeds size limit')
        return value


def clear_staging(store, pattern):
    for stale in store.glob(pattern):
        backup.private_directory(stale)
        shutil.rmtree(stale)


def export_backup(source, store, recipient_file):
    with backup.locked(source.parent), backup.locked(store):
        return export_locked(source, store, recipient_file)


def export_locked(source, store, recipient_file):
    """Caller holds both capture-retention and export-store locks."""
    recipient = read_recipient(recipient_file)
    backup.private_directory(store)
    backup.require(source.parent.resolve() != store.resolve(), 'Use a separate export store')
    clear_staging(store, '.pending-export-*')
    backup.validate_backup(source)
    archive = backup.read_regular(source / 'snapshot.tar', backup.ARCHIVE_LIMIT, 0o600)
    stage = Path(tempfile.mkdtemp(prefix='.pending-export-', dir=store))
    try:
        encrypted = age_transform(archive, ['--encrypt', '--recipient', recipient], stage, CIPHER_LIMIT)
        backup.write_private(stage / 'snapshot.tar.age', encrypted)
        backup.require(backup.read_regular(stage / 'snapshot.tar.age', CIPHER_LIMIT, 0o600) == encrypted,
                       'Encrypted output verification failed')
        backup.sync_directory(stage)
        captured = dt.datetime.now(dt.timezone.utc)
        target = store / (captured.strftime('export-%Y%m%dT%H%M%S%fZ-') + uuid.uuid4().hex[:8])
        os.rename(stage, target)
        backup.sync_directory(store)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    # No pruning on encryption/publication failure; retain the new export even after clock rollback.
    completed = sorted(p for p in store.iterdir() if EXPORT_NAME.fullmatch(p.name) and p != target)
    for old in completed[:-(KEEP - 1)]:
        backup.private_directory(old)
        shutil.rmtree(old)
    backup.sync_directory(store)
    return target

@contextlib.contextmanager
def decrypted_backup(encrypted_file, identity_file, work_dir):
    backup.private_directory(work_dir)
    backup.private_directory(encrypted_file.parent)
    encrypted = backup.read_regular(encrypted_file, CIPHER_LIMIT, 0o600)
    identity = read_identity(identity_file)
    with tempfile.TemporaryDirectory(prefix='.decrypt-', dir=work_dir) as temporary:
        directory = Path(temporary)
        key = directory / 'identity.txt'
        backup.write_private(key, identity)
        plaintext = age_transform(encrypted, ['--decrypt', '--identity', str(key)], directory,
                                  backup.ARCHIVE_LIMIT)
        key.unlink()
        snapshot = directory / 'snapshot'
        snapshot.mkdir(mode=0o700)
        backup.write_private(snapshot / 'snapshot.tar', plaintext)
        backup.write_private(snapshot / 'sha256', (backup.digest(plaintext) + '\n').encode())
        backup.validate_backup(snapshot)
        yield snapshot


def verify_export(encrypted_file, identity_file, work_dir):
    with backup.locked(work_dir):
        clear_staging(work_dir, '.decrypt-*')
        with decrypted_backup(encrypted_file, identity_file, work_dir):
            return True


def restore_export(encrypted_file, destination, identity_file, work_dir):
    backup.private_directory(destination.parent)
    backup.require(not destination.exists() and not destination.is_symlink(),
                   'Restore destination already exists; use a new name')
    # Serialize restores even when callers select different work directories.
    with contextlib.ExitStack() as locks:
        for directory in sorted({work_dir.resolve(), destination.parent.resolve()}):
            locks.enter_context(backup.locked(directory))
        clear_staging(work_dir, '.decrypt-*')
        with decrypted_backup(encrypted_file, identity_file, work_dir) as snapshot:
            return backup.restore_backup(snapshot, destination)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    export = commands.add_parser('export')
    export.add_argument('backup_directory', type=Path)
    export.add_argument('output_store', type=Path)
    export.add_argument('--recipient-file', required=True, type=Path)
    for command in ['verify', 'restore']:
        sub = commands.add_parser(command)
        sub.add_argument('encrypted_file', type=Path)
        if command == 'restore':
            sub.add_argument('destination', type=Path)
        sub.add_argument('--identity-file', required=True, type=Path)
        sub.add_argument('--work-dir', required=True, type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    started = time.monotonic()
    result = {'result': args.command + '-complete'}
    if args.command == 'export':
        target = export_backup(args.backup_directory.absolute(), args.output_store.absolute(),
                               args.recipient_file.absolute())
        result['export'] = target.name
    elif args.command == 'verify':
        verify_export(args.encrypted_file.absolute(), args.identity_file.absolute(), args.work_dir.absolute())
        result['authenticatedAndValidated'] = True
    else:
        restore_export(args.encrypted_file.absolute(), args.destination.absolute(),
                       args.identity_file.absolute(), args.work_dir.absolute())
        result['hashesAndModesVerified'] = True
    result['durationMs'] = round((time.monotonic() - started) * 1000)
    print(json.dumps(result))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, tarfile.TarError, KeyError, TypeError, subprocess.SubprocessError) as error:
        allowed = {'Another backup or restore is running', 'Restore destination already exists; use a new name',
                   'age operation failed; check key and encrypted input', 'Install age before export or recovery',
                   'Application session validation failed', 'Archive path or duplicate member rejected',
                   'Payload integrity mismatch', 'Input permission mismatch'}
        reason = str(error) if type(error) is ValueError and str(error) in allowed else type(error).__name__
        print('Encrypted backup failed: ' + reason + '; inspect inputs, key availability, ownership and modes.',
              file=sys.stderr)
        sys.exit(1)

#!/usr/bin/env python3
"""Small, private snapshots of the local Linux session and environment file."""

import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import subprocess
import tarfile
import tempfile
import time
import uuid

STORE = Path('/var/lib/pink-party-backups')
RESTORES = Path('/var/lib/pink-party-restores')
SOURCES = {
    'data/session.json': Path('/opt/pink-party/app/data/session.json'),
    'private/pink-party.env': Path('/etc/pink-party/pink-party.env'),
}
MODES = {'data/session.json': 0o644, 'private/pink-party.env': 0o600}
LIMIT = 16384
ARCHIVE_LIMIT = 65536
KEEP = 7
NAME = re.compile(r'backup-\d{8}T\d{12}Z-[a-f0-9]{8}')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def private_directory(path):
    info = path.lstat()
    require(stat.S_ISDIR(info.st_mode) and info.st_uid == os.geteuid()
            and stat.S_IMODE(info.st_mode) == 0o700,
            'Directory must be owned by the operator with mode 0700')
    require(path.resolve() == path.absolute(), 'Symlinked directory path rejected')


def read_regular(path, limit, mode=None):
    # Never follow a final symlink or block opening a FIFO. Parents are trusted directories.
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, 'rb') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_nlink == 1
                and info.st_uid == os.geteuid(), 'Input must be an owned regular file')
        if mode is not None:
            require(stat.S_IMODE(info.st_mode) == mode, 'Input permission mismatch')
        require(info.st_size <= limit, 'Input exceeds size limit')
        data = stream.read(limit + 1)
        require(len(data) <= limit, 'Input exceeds size limit')
        return data


def write_private(path, data, mode=0o600):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, mode)
    with os.fdopen(fd, 'wb') as stream:
        os.fchmod(stream.fileno(), mode)
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


@contextlib.contextmanager
def locked(store):
    private_directory(store)
    fd = os.open(store / '.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+') as stream:
        info = os.fstat(stream.fileno())
        require(stat.S_ISREG(info.st_mode) and info.st_uid == os.geteuid()
                and info.st_nlink == 1 and stat.S_IMODE(info.st_mode) == 0o600,
                'Unsafe backup lock')
        try:
            fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('Another backup or restore is running') from None
        yield


def validate_payloads(payloads):
    # Reuse the application's boundary instead of maintaining a second session schema.
    module = (Path(__file__).resolve().parents[2] / 'server/session.ts').as_uri()
    node = '/opt/pink-party/node/bin/node' if Path('/opt/pink-party/node/bin/node').is_file() else shutil.which('node')
    require(node is not None, 'Node.js 24 is required for session validation')
    result = subprocess.run([node, '--input-type=module', '-e',
                             'import {validateSession} from ' + json.dumps(module) + ';'
                             'import {readFileSync} from "node:fs";'
                             'validateSession(JSON.parse(readFileSync(0, "utf8")));'],
                            input=payloads['data/session.json'], stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL, timeout=5, env={'PATH': os.defpath})
    require(result.returncode == 0, 'Application session validation failed')
    # This backup format is deliberately limited to the generated Linux local configuration.
    lines = payloads['private/pink-party.env'].decode('ascii').splitlines()
    fields = dict(line.split('=', 1) for line in lines)
    require(len(lines) == len(fields) == 4 and set(fields) == {
        'PINK_PARTY_MODE', 'JOIN_CODE', 'LIVEKIT_API_KEY', 'LIVEKIT_API_SECRET'
    } and fields['PINK_PARTY_MODE'] == 'local', 'Unsupported local configuration')
    for key, minimum in [('JOIN_CODE', 16), ('LIVEKIT_API_KEY', 12), ('LIVEKIT_API_SECRET', 32)]:
        value = fields[key]
        require(bool(re.fullmatch(r'[a-zA-Z0-9_-]+', value))
                and minimum <= len(value) <= 128 and not value.startswith('replace-'),
                'Invalid local configuration')


def validate_backup(directory):
    private_directory(directory)
    require({p.name for p in directory.iterdir()} == {'snapshot.tar', 'sha256'},
            'Unexpected backup files')
    archive = read_regular(directory / 'snapshot.tar', ARCHIVE_LIMIT, 0o600)
    checksum = read_regular(directory / 'sha256', 65, 0o600)
    require(checksum == (digest(archive) + '\n').encode(), 'Archive checksum mismatch')
    payloads = {}
    with tarfile.open(fileobj=io.BytesIO(archive), mode='r:') as tar:
        for member in tar:
            require(member.name in {*MODES, 'manifest.json'} and member.name not in payloads,
                    'Archive path or duplicate member rejected')
            require(member.type == tarfile.REGTYPE and not member.pax_headers
                    and not member.linkname and member.uid == member.gid == 0
                    and 0 < member.size <= LIMIT
                    and member.mode == MODES.get(member.name, 0o600),
                    'Archive type, size or permission rejected')
            payloads[member.name] = tar.extractfile(member).read(LIMIT + 1)
    require(set(payloads) == {*MODES, 'manifest.json'}, 'Archive members missing')
    manifest = json.loads(payloads.pop('manifest.json'))
    require(isinstance(manifest, dict) and set(manifest) == {'version', 'capturedAt', 'files'}
            and manifest['version'] == 1 and isinstance(manifest['capturedAt'], str)
            and dt.datetime.fromisoformat(manifest['capturedAt']).tzinfo is not None,
            'Invalid backup manifest')
    expected = {name: {'sha256': digest(data), 'bytes': len(data), 'mode': MODES[name]}
                for name, data in payloads.items()}
    require(manifest['files'] == expected, 'Payload integrity mismatch')
    validate_payloads(payloads)
    return payloads, manifest


def create_backup(sources=SOURCES, store=STORE):
    with locked(store):
        # A killed/expired job can leave a private staging directory. No completed name is removed here.
        for stale in store.glob('.pending-*'):
            private_directory(stale)
            shutil.rmtree(stale)
        payloads = {name: read_regular(sources[name], LIMIT, MODES[name]) for name in MODES}
        validate_payloads(payloads)
        captured = dt.datetime.now(dt.timezone.utc)
        manifest = {'version': 1, 'capturedAt': captured.isoformat(), 'files': {
            name: {'sha256': digest(data), 'bytes': len(data), 'mode': MODES[name]}
            for name, data in payloads.items()
        }}
        stage = Path(tempfile.mkdtemp(prefix='.pending-', dir=store))
        try:
            buffer = io.BytesIO()
            with tarfile.open(fileobj=buffer, mode='w', format=tarfile.USTAR_FORMAT) as tar:
                for name, data in {**payloads, 'manifest.json': json.dumps(manifest).encode()}.items():
                    member = tarfile.TarInfo(name)
                    member.size, member.mode = len(data), MODES.get(name, 0o600)
                    tar.addfile(member, io.BytesIO(data))
            write_private(stage / 'snapshot.tar', buffer.getvalue())
            write_private(stage / 'sha256', (digest(buffer.getvalue()) + '\n').encode())
            require(validate_backup(stage)[0] == payloads, 'Backup verification mismatch')
            require(all(read_regular(sources[name], LIMIT, MODES[name]) == data
                        for name, data in payloads.items()), 'Source changed during capture; retry')
            sync_directory(stage)
            target = store / (captured.strftime('backup-%Y%m%dT%H%M%S%fZ-') + uuid.uuid4().hex[:8])
            os.rename(stage, target)
            sync_directory(store)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
        # Prune only after a verified backup has been published. Never prune on capture failure.
        completed = sorted(p for p in store.iterdir() if NAME.fullmatch(p.name) and p != target)
        for old in completed[:-(KEEP - 1)]:
            private_directory(old)
            shutil.rmtree(old)
        sync_directory(store)
        return target, manifest


def restore_backup(backup, destination):
    private_directory(destination.parent)
    require(re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}', destination.name),
            'Invalid restore directory name')
    require(not destination.exists() and not destination.is_symlink(),
            'Restore destination already exists; use a new name')
    with locked(backup.parent):
        payloads, manifest = validate_backup(backup)
        stage = Path(tempfile.mkdtemp(prefix='.restore-', dir=destination.parent))
        try:
            for folder in ['data', 'private']:
                (stage / folder).mkdir(mode=0o700)
            # All archive checks finish before any payload is written. No extractall or archive paths in filesystem calls.
            for name in MODES:
                write_private(stage / name, payloads[name], MODES[name])
                require(read_regular(stage / name, LIMIT, MODES[name]) == payloads[name],
                        'Restored content mismatch')
            for folder in ['data', 'private']:
                private_directory(stage / folder)
                sync_directory(stage / folder)
            sync_directory(stage)
            os.rename(stage, destination)
            sync_directory(destination.parent)
        finally:
            if stage.exists():
                shutil.rmtree(stage)
        return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('create')
    restore = commands.add_parser('restore')
    restore.add_argument('backup_name')
    restore.add_argument('restore_name')
    args = parser.parse_args()
    require(sys.platform == 'linux' and os.geteuid() == 0, 'Run as root inside the Linux lab')
    os.umask(0o077)
    started = time.monotonic()
    if args.command == 'create':
        path, _ = create_backup()
        print(json.dumps({'result': 'backup-complete', 'backup': path.name,
                          'durationMs': round((time.monotonic() - started) * 1000)}))
    else:
        require(NAME.fullmatch(args.backup_name), 'Invalid backup name')
        restore_backup(STORE / args.backup_name, RESTORES / args.restore_name)
        print(json.dumps({'result': 'restore-complete', 'hashesAndModesVerified': True,
                          'durationMs': round((time.monotonic() - started) * 1000)}))


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, tarfile.TarError, KeyError, TypeError, subprocess.SubprocessError) as error:
        # Payloads, paths and exception strings may contain private data. Emit only a bounded reason.
        reason = str(error) if type(error) is ValueError else type(error).__name__
        allowed = {'Another backup or restore is running', 'Archive checksum mismatch',
                   'Archive path or duplicate member rejected', 'Payload integrity mismatch',
                   'Restore destination already exists; use a new name',
                   'Source changed during capture; retry', 'Input permission mismatch',
                   'Application session validation failed'}
        print('Backup/restore failed: ' + (reason if reason in allowed else type(error).__name__)
              + '; inspect unit status, file existence, ownership and modes.', file=sys.stderr)
        sys.exit(1)

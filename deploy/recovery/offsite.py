#!/usr/bin/env python3
"""Copy authenticated captures to a dedicated SFTP directory and verify by retrieval."""

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import re
import resource
import subprocess
import sys
import tempfile

from collector import (ATTEMPT_MAX, CAPTURE_MAX, KEEP, Fault, age, authenticate, backup,
                       bounded_run, check_state, check_store, configuration as collection_config,
                       encrypted, instant, now, read_json, read_state, require, run_job)

MARKER = 'pink-party-rolling-v1'
MARKER_BYTES = b'Pink Party dedicated rolling ciphertexts v1\n'
PENDING = '.incoming'
NAME = re.compile(r'capture-\d{8}T\d{12}Z-[a-f0-9]{64}\.age')
DIGEST = re.compile(r'[a-f0-9]{64}')
SFTP_SECONDS = 12


def private_path(value):
    require(isinstance(value, str) and Path(value).is_absolute(), 'config-invalid')
    path = Path(value)
    backup.private_directory(path.parent)
    return path


def configuration(path, writer):
    backup.private_directory(path.parent)
    config = read_json(path)
    fields = {'version', 'sshConfig', 'directory'}
    require(isinstance(config, dict) and config.keys() == (
        fields | {'collectionConfig', 'state'} if writer else fields)
        and type(config['version']) is int and config['version'] == 1, 'config-invalid')
    require(isinstance(config['directory'], str) and
            re.fullmatch(r'(/[-a-zA-Z0-9_]{1,80}){1,12}', config['directory']), 'config-invalid')
    config['sshConfig'] = private_path(config['sshConfig'])
    ssh_config = backup.read_regular(config['sshConfig'], 16384, 0o600)
    config['destinationBinding'] = backup.digest(config['directory'].encode() + b'\0' + ssh_config)
    if writer:
        config['collectionConfig'] = private_path(config['collectionConfig'])
        config['state'] = private_path(config['state'])
        backup.private_directory(config['state'])
        collection = collection_config(config['collectionConfig'])
        require(all(config['state'] != p and config['state'] not in p.parents
                    and p not in config['state'].parents
                    for p in [collection['state'], collection['store'], collection['identity'].parent]),
                'config-overlap')
    return config


def sftp_limits():
    resource.setrlimit(resource.RLIMIT_FSIZE, (encrypted.CIPHER_LIMIT, encrypted.CIPHER_LIMIT))
    resource.setrlimit(resource.RLIMIT_CORE, (0, 0))


class Sftp:
    def __init__(self, config, command=None):
        self.directory = config['directory']
        self.command = command or [
            '/usr/bin/sftp', '-F', str(config['sshConfig']), '-oBatchMode=yes',
            '-oStrictHostKeyChecking=yes', '-oConnectionAttempts=1', '-oConnectTimeout=5',
            '-oClearAllForwardings=yes', '-oForwardAgent=no', '-oControlPath=none',
            '-oUpdateHostKeys=no', '-b', '-', 'pink-party-backup',
        ]

    def execute(self, work, commands):
        with tempfile.TemporaryFile(dir=work) as output, tempfile.TemporaryFile(dir=work) as errors:
            try:
                result = subprocess.run(
                    self.command, input=('\n'.join(['@cd ' + self.directory, *commands]) + '\n').encode(),
                    cwd=work, stdout=output, stderr=errors, timeout=SFTP_SECONDS, preexec_fn=sftp_limits)
            except subprocess.TimeoutExpired:
                raise Fault('destination-timeout') from None
            if result.returncode:
                errors.seek(0)
                diagnostic = errors.read(8192).lower()
                if b'permission denied' in diagnostic or b'authentication failed' in diagnostic:
                    raise Fault('destination-access-denied')
                if b'no space' in diagnostic or b'quota' in diagnostic:
                    raise Fault('destination-quota')
                # SFTP servers can report several distinct faults as a generic Failure.
                raise Fault('destination-or-transfer-failed')
            output.seek(0)
            return output.read().decode('ascii')

    def inventory(self, work):
        entries = {}
        for row in self.execute(work, ['@ls -lna']).splitlines():
            columns = row.split(maxsplit=8)
            require(len(columns) == 9, 'remote-inventory-invalid')
            mode, *_, name = columns
            if name in {'.', '..'}:
                continue
            require(mode == '-rw-------' and name not in entries
                    and (name in {MARKER, PENDING} or NAME.fullmatch(name)), 'remote-inventory-invalid')
            size = columns[4]
            require(size.isdecimal() and len(size) <= 7 and int(size) <= encrypted.CIPHER_LIMIT,
                    'remote-object-too-large')
            entries[name] = int(size)
        return entries

    def get(self, work, name, local):
        require(name in {MARKER, PENDING} or NAME.fullmatch(name), 'object-name-invalid')
        # Pre-create the local file with a private mode independent of the remote mode.
        path = work / local
        backup.write_private(path, b'')
        self.execute(work, [f'@get {name} {local}'])
        return path


def check_inventory(remote, work):
    entries = remote.inventory(work)
    require(MARKER in entries, 'remote-store-uninitialized')
    marker = remote.get(work, MARKER, 'marker')
    require(backup.read_regular(marker, 128, 0o600) == MARKER_BYTES, 'remote-store-invalid')
    copies = sorted(set(entries) - {MARKER, PENDING})
    require(len(copies) <= KEEP + 1 and not (len(copies) == KEEP + 1 and PENDING in entries), 'remote-store-full')
    return copies


def object_name(captured, digest):
    require(isinstance(digest, str) and DIGEST.fullmatch(digest), 'state-invalid')
    stamp = instant(captured).astimezone(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    name = f'capture-{stamp}-{digest}.age'
    require(NAME.fullmatch(name), 'state-invalid')
    return name


def verify_cipher(path, identity, work, name, record=None):
    data = backup.read_regular(path, encrypted.CIPHER_LIMIT, 0o600)
    if record and record.get('remoteCipherDigest'):
        require(backup.digest(data) == record['remoteCipherDigest'], 'remote-copy-changed')
    manifest, digest = authenticate(path, identity, work, record)
    require(object_name(manifest['capturedAt'], digest) == name, 'remote-capture-mismatch')
    return manifest['capturedAt'], backup.digest(data)


def validate_record(record, at, binding, fresh=True):
    require(record['object'] == object_name(record['capturedAt'], record['archiveDigest'])
            and DIGEST.fullmatch(record['remoteCipherDigest']), 'state-invalid')
    require(record['destinationBinding'] == binding, 'destination-config-changed')
    timeline = [record['capturedAt'], record['exportedAt'], record['collectedAt'],
                record['localAuthenticatedAt'], record['retrievedAt'], record['authenticatedAt']]
    require(timeline == sorted(timeline, key=instant), 'clock-skew')
    age(timeline[-1], at, ATTEMPT_MAX if fresh else float('inf'))
    if record['transferredAt'] is not None:
        age(record['transferredAt'], record['retrievedAt'], float('inf'))
        age(record['capturedAt'], record['transferredAt'], float('inf'))
    if fresh:
        age(record['capturedAt'], at, CAPTURE_MAX)


def local_copy(config, work):
    collection = collection_config(config['collectionConfig'])
    with backup.locked(collection['store']):
        check_store(collection['store'])
        at = now()
        state = read_state(collection['state'])
        record = check_state(state, at, ATTEMPT_MAX)
        times = [instant(record[key]) for key in ['capturedAt', 'exportedAt', 'collectedAt', 'validatedAt']]
        require(times == sorted(times) and instant(state['attemptedAt']) <= times[-1]
                <= instant(state['finishedAt']), 'collection-timestamp-invalid')
        require(encrypted.EXPORT_NAME.fullmatch(record['export']), 'state-invalid')
        path = collection['store'] / (record['export'] + '.age')
        data = backup.read_regular(path, encrypted.CIPHER_LIMIT, 0o600)
        require(backup.digest(data) == record['cipherDigest'], 'local-copy-changed')
    staged = work / 'upload.age'
    backup.write_private(staged, data)
    name = object_name(record['capturedAt'], record['archiveDigest'])
    verify_cipher(staged, collection['identity'], work, name, record)
    return name, record, collection['identity']


def transfer(config, previous, remote):
    if previous:
        validate_record(previous, now(), config['destinationBinding'], fresh=False)
    encrypted.clear_staging(config['state'], '.offsite-*')
    with tempfile.TemporaryDirectory(prefix='.offsite-', dir=config['state']) as temporary:
        work = Path(temporary)
        name, record, identity = local_copy(config, work)
        copies = check_inventory(remote, work)
        protected = previous['object'] if previous else None
        if previous:
            require(instant(record['capturedAt']) >= instant(previous['capturedAt']), 'capture-rollback')
            require(protected in copies, 'remote-copy-missing')
        # Preserve and authenticate the previous success before any mutation.
        if protected and protected != name:
            prior = remote.get(work, protected, 'previous.age')
            verify_cipher(prior, identity, work, protected, previous)
        transferred = previous['transferredAt'] if protected == name else None
        if name not in copies:
            require(len(copies) < KEEP + 1, 'remote-store-full')
            remote.execute(work, [f'@put upload.age {PENDING}', f'@chmod 600 {PENDING}'])
            candidate = remote.get(work, PENDING, 'staged.age')
            verify_cipher(candidate, identity, work, name, {**record, 'remoteCipherDigest': record['cipherDigest']})
            remote.execute(work, [f'@rename {PENDING} {name}'])
            transferred = now()
            copies.append(name)
        final = remote.get(work, name, 'retrieved.age')
        retrieved = now()
        expected = previous if protected == name else record
        if transferred is not None and protected != name:
            expected = {**record, 'remoteCipherDigest': record['cipherDigest']}
        captured, digest = verify_cipher(final, identity, work, name, expected)
        success = dict(object=name, capturedAt=captured, archiveDigest=record['archiveDigest'],
                       destinationBinding=config['destinationBinding'],
                       remoteCipherDigest=digest, exportedAt=record['exportedAt'], collectedAt=record['collectedAt'],
                       localAuthenticatedAt=record['validatedAt'], transferredAt=transferred,
                       retrievedAt=retrieved, authenticatedAt=now())
        validate_record(success, now(), config['destinationBinding'])
        if len(copies) > KEEP:
            oldest = next(p for p in sorted(copies) if p not in {protected, name})
            remote.execute(work, [f'@rm {oldest}'])
        return success, 'retrieved-and-validated'


def initialize_remote(remote, work):
    require(not remote.inventory(work), 'remote-store-not-empty')
    backup.write_private(work / 'marker', MARKER_BYTES)
    remote.execute(work, [f'@put marker {MARKER}', f'@chmod 600 {MARKER}'])


def retrieve(remote, name, identity, destination):
    require(NAME.fullmatch(name), 'object-name-invalid')
    backup.private_directory(destination.parent)
    with backup.locked(destination.parent):
        encrypted.clear_staging(destination.parent, '.retrieve-*')
        require(not destination.exists() and not destination.is_symlink(), 'destination-exists')
        with tempfile.TemporaryDirectory(prefix='.retrieve-', dir=destination.parent) as temporary:
            work = Path(temporary)
            ciphertext = remote.get(work, name, 'retrieved.age')
            retrieved = now()
            captured, _ = verify_cipher(ciphertext, identity, work, name)
            age(captured, now(), float('inf'))
            with ciphertext.open('rb') as stream:
                os.fsync(stream.fileno())
            backup.sync_directory(work)
            os.link(ciphertext, destination)
            ciphertext.unlink()
            backup.sync_directory(destination.parent)
            return dict(capturedAt=captured, retrievedAt=retrieved, authenticatedAt=now())


def inspect(config):
    at = now()
    state = None
    report = dict(observedAt=at, healthy=False)
    try:
        state = read_state(config['state'])
        if state and state['outcome'] == 'error':
            raise Fault('job-error:' + state['reason'])
        success = check_state(state, at, ATTEMPT_MAX)
        validate_record(success, at, config['destinationBinding'])
        require(instant(state['attemptedAt']) <= instant(success['retrievedAt'])
                <= instant(success['authenticatedAt']) <= instant(state['finishedAt']), 'state-invalid')
        report.update(healthy=True, reason='recent-validated-retrieval')
    except (OSError, ValueError, KeyError, TypeError) as error:
        report['reason'] = str(error) if isinstance(error, Fault) else 'state-invalid'
    report['attemptedAt'] = state['attemptedAt'] if state else None
    report['finishedAt'] = state['finishedAt'] if state else None
    success = state['success'] if state else None
    for field in ['capturedAt', 'exportedAt', 'collectedAt', 'localAuthenticatedAt', 'transferredAt',
                  'retrievedAt', 'authenticatedAt']:
        value = success.get(field) if success else None
        try:
            instant(value)
        except Fault:
            value = None
        report[field] = value
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['init', 'run', 'inspect', 'list', 'retrieve'])
    parser.add_argument('config', type=Path)
    parser.add_argument('--object')
    parser.add_argument('--identity', type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--worker', action='store_true', help=argparse.SUPPRESS)
    args = parser.parse_args()
    os.umask(0o077)
    if args.command in {'init', 'run', 'list', 'retrieve'} and not args.worker:
        return bounded_run(args.config, Path(__file__), 110, [*sys.argv[1:], '--worker'])
    writer = args.command in {'init', 'run', 'inspect'}
    config = configuration(args.config, writer)
    remote = Sftp(config)
    if args.command == 'run':
        run_job(config['state'], lambda previous: transfer(config, previous, remote))
        print('Remote retrieval authenticated and validated.')
    elif args.command == 'inspect':
        result = inspect(config)
        print(json.dumps(result))
        return 0 if result['healthy'] else 1
    elif args.command == 'retrieve':
        require(args.object and args.identity and args.output, 'recovery-inputs-required')
        print(json.dumps(retrieve(remote, args.object, args.identity, args.output)))
    elif args.command == 'list':
        with backup.locked(args.config.parent):
            encrypted.clear_staging(args.config.parent, '.list-*')
            with tempfile.TemporaryDirectory(prefix='.list-', dir=args.config.parent) as temporary:
                print('\n'.join(check_inventory(remote, Path(temporary))))
    else:
        with backup.locked(config['state']):
            encrypted.clear_staging(config['state'], '.offsite-*')
            with tempfile.TemporaryDirectory(prefix='.offsite-', dir=config['state']) as temporary:
                initialize_remote(remote, Path(temporary))
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print('Off-device backup failed: ' + (
            str(error) if isinstance(error, Fault) else 'private-input-or-state-error'), file=sys.stderr)
        sys.exit(1)

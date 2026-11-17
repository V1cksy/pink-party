#!/usr/bin/env python3
"""Run encrypted-input failure boundaries while preserving a healthy recovery deployment."""

import argparse
import importlib.util
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import tarfile
import time
import uuid

spec = importlib.util.spec_from_file_location('encrypted', Path(__file__).with_name('encrypted-backup.py'))
encrypted = importlib.util.module_from_spec(spec)
spec.loader.exec_module(encrypted)
b = encrypted.backup


def exercise(cipher, key):
    os.umask(0o077)
    work = b.RESTORES / ('encrypted-exercise-' + uuid.uuid4().hex[:12])
    work.mkdir(mode=0o700)
    for name in ['input', 'keys', 'scratch', 'restores', 'exports', 'snapshots']:
        (work / name).mkdir(mode=0o700)
    before = {name: b.read_regular(path, b.LIMIT, b.MODES[name]) for name, path in b.SOURCES.items()}
    cipher_before = b.read_regular(cipher, encrypted.CIPHER_LIMIT, 0o600)
    pid = subprocess.check_output(['systemctl', 'show', 'pink-party.service', '-p', 'MainPID', '--value'], timeout=5)
    passed = []
    public = subprocess.check_output(['age-keygen', '-y', str(key)], stderr=subprocess.DEVNULL, timeout=5)
    recipient = work / 'keys/recipient.txt'
    b.write_private(recipient, public)
    good = b.create_backup(store=work / 'snapshots')[0]
    export = encrypted.export_backup(good, work / 'exports', recipient)
    prior = b.read_regular(export / 'snapshot.tar.age', encrypted.CIPHER_LIMIT, 0o600)

    def unchanged():
        subprocess.run(['/opt/pink-party/node/bin/node', '/opt/pink-party/app/deploy/linux/service-health.ts'], check=True, timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        b.require(all(b.read_regular(b.SOURCES[name], b.LIMIT, b.MODES[name]) == data for name, data in before.items()), 'Working files changed')
        b.require(subprocess.check_output(['systemctl', 'show', 'pink-party.service', '-p', 'MainPID', '--value'], timeout=5) == pid, 'Healthy service replaced')
        b.require(b.read_regular(cipher, encrypted.CIPHER_LIMIT, 0o600) == cipher_before, 'Recovery export changed')
        b.require(b.read_regular(export / 'snapshot.tar.age', encrypted.CIPHER_LIMIT, 0o600) == prior, 'Prior good export changed')

    def reject(label, path=cipher, identity=key):
        target = work / 'restores' / label
        try:
            encrypted.restore_export(path, target, identity, work / 'scratch')
        except (ValueError, OSError, tarfile.TarError, KeyError, TypeError):
            b.require(not target.exists(), 'Rejected input published a destination')
            unchanged()
            passed.append(label)
            return
        raise ValueError('Invalid recovery input accepted')

    reject('missing-key', identity=work / 'keys/missing.agekey')
    wrong = work / 'keys/wrong.agekey'
    subprocess.run(['age-keygen', '-o', str(wrong)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5)
    reject('wrong-key', identity=wrong)
    unavailable = work / 'keys/unavailable.agekey'
    b.write_private(unavailable, encrypted.read_identity(key))
    unavailable.chmod(0)
    reject('unavailable-key', identity=unavailable)
    unavailable.chmod(0o600)
    for label, data in [('corrupt', cipher_before[:100] + bytes([cipher_before[100] ^ 1]) + cipher_before[101:]),
                        ('truncated', cipher_before[:-20])]:
        path = work / 'input' / (label + '.age')
        b.write_private(path, data)
        reject(label, path)
    archive = encrypted.age_transform(cipher_before, ['--decrypt', '--identity', str(key)], work / 'scratch', b.ARCHIVE_LIMIT)
    for label in ['archive', 'schema', 'path']:
        if label == 'archive':
            modified = b'invalid tar archive'
        else:
            buffer = io.BytesIO()
            with tarfile.open(fileobj=io.BytesIO(archive), mode='r:') as source:
                files = {member.name: source.extractfile(member).read() for member in source}
            if label == 'schema':
                session = json.loads(files['data/session.json'])
                del session['game']
                files['data/session.json'] = json.dumps(session).encode()
                manifest = json.loads(files['manifest.json'])
                manifest['files']['data/session.json'].update(sha256=b.digest(files['data/session.json']), bytes=len(files['data/session.json']))
                files['manifest.json'] = json.dumps(manifest).encode()
            with tarfile.open(fileobj=buffer, mode='w', format=tarfile.USTAR_FORMAT) as target:
                for name, data in files.items():
                    member = tarfile.TarInfo('../escape' if label == 'path' and name == 'data/session.json' else name)
                    member.size, member.mode = len(data), b.MODES.get(name, 0o600)
                    target.addfile(member, io.BytesIO(data))
            modified = buffer.getvalue()
        path = work / 'input' / (label + '.age')
        b.write_private(path, encrypted.age_transform(modified, ['-r', public.decode().strip()], work / 'scratch', encrypted.CIPHER_LIMIT))
        reject(label, path)
    existing = work / 'restores/existing'
    encrypted.restore_export(cipher, existing, key, work / 'scratch')
    try:
        encrypted.restore_export(cipher, existing, key, work / 'scratch')
    except ValueError:
        b.require(all(b.read_regular(existing / name, b.LIMIT, b.MODES[name]) == data for name, data in before.items()), 'Existing restore changed')
        passed.append('existing-destination')
    else:
        raise ValueError('Existing destination accepted')
    (good / 'snapshot.tar').chmod(0o644)
    try:
        encrypted.export_backup(good, work / 'exports', recipient)
    except ValueError:
        unchanged()
        passed.append('failed-export-permissions')
    else:
        raise ValueError('Bad-permission snapshot exported')
    finally:
        (good / 'snapshot.tar').chmod(0o600)
    # A blocking age stand-in makes interruption of these tiny CLI operations reproducible.
    # Kill the actual CLI and its child group before any output can be accepted.
    fake = work / 'fake-bin'
    fake.mkdir(mode=0o700)
    (fake / 'age').write_text('#!/bin/sh\nsleep 30\n')
    (fake / 'age').chmod(0o700)
    for operation in ['export', 'restore']:
        destination = work / 'restores/interrupted'
        args = ([str(good), str(work / 'exports'), '--recipient-file', str(recipient)] if operation == 'export' else
                [str(cipher), str(destination), '--identity-file', str(key), '--work-dir', str(work / 'scratch')])
        child = subprocess.Popen(['/usr/bin/python3', '-B', str(Path(__file__).with_name('encrypted-backup.py')), operation, *args],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True,
                                 env={**os.environ, 'PATH': str(fake) + ':/usr/bin:/bin'})
        try:
            deadline = time.monotonic() + 5
            pattern = '.pending-export-*' if operation == 'export' else '.decrypt-*'
            parent = work / ('exports' if operation == 'export' else 'scratch')
            while time.monotonic() < deadline and not list(parent.glob(pattern)) and child.poll() is None:
                time.sleep(0.05)
            b.require(child.poll() is None and list(parent.glob(pattern)), 'Interrupt exercise did not reach staging')
        finally:
            if child.poll() is None:
                os.killpg(child.pid, signal.SIGTERM)
            child.wait(timeout=5)
        unchanged()
        b.require(not destination.exists(), 'Interrupted restore published output')
        passed.append('interrupted-' + operation)
    encrypted.verify_export(cipher, key, work / 'scratch')
    encrypted.export_backup(good, work / 'exports', recipient)
    unchanged()
    report = {'scope': 'Codex-run assisted encrypted failure exercises on healthy fresh guest',
              'rejectedWithoutChangingHealthyFilesPidOrPriorGoodExport': passed,
              'normalAuthenticationAndExportAfterInterruption': True,
              'realRetainedRecoveryKeyUnchanged': encrypted.read_identity(key) is not None}
    b.write_private(work / 'report.json', (json.dumps(report, indent=2) + '\n').encode())
    print('Encrypted failure exercises passed: ' + str(len(passed)) + '; healthy deployment and prior good recovery material unchanged.')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('encrypted', type=Path)
    parser.add_argument('identity', type=Path)
    args = parser.parse_args()
    exercise(args.encrypted, args.identity)

#!/usr/bin/env python3
"""Inject one bounded source-export fault; restore protected files before another case."""

import argparse
import datetime as dt
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tarfile
import re

from freshness import backup, atomic_json, read_json, now, require

WORK = Path('/var/lib/pink-party-restores/batch10-export-faults')
EXPORTS = Path('/var/lib/pink-party-rolling-exports')
ES = Path('/var/lib/pink-party-export-status/status.json')
BS = Path('/var/lib/pink-party-backup-status/status.json')
RECIPIENT = Path('/var/lib/pink-party-export-config/recipient.txt')


def ctl(*args):
    subprocess.run(['systemctl', *args], check=True, timeout=15,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def pause():
    ctl('stop', 'pink-party-backup.timer', 'pink-party-backup.service',
        'pink-party-export.timer', 'pink-party-export.service')


def validate_workspace():
    # Validate the recovery checkpoint before touching a timer or live capture. A typo must be harmless.
    backup.private_directory(WORK)
    backup.private_directory(WORK / 'backups')
    captures = [p for p in (WORK / 'backups').iterdir() if backup.NAME.fullmatch(p.name)]
    require(0 < len(captures) <= backup.KEEP, 'invalid-protected-captures')
    validated = {}
    for path in captures:
        _, manifest = backup.validate_backup(path)
        digest = backup.digest(backup.read_regular(path / 'snapshot.tar', backup.ARCHIVE_LIMIT, 0o600))
        validated[digest] = (path.name, manifest['capturedAt'])
    bs, es = read_json(WORK / 'backup-status.json'), read_json(WORK / 'export-status.json')
    for state in [bs, es]:
        require(isinstance(state, dict) and state.get('version') == 1 and isinstance(state.get('success'), dict),
                'invalid-protected-status')
        record = state['success']
        require(record.get('archiveDigest') in validated and
                record.get('capturedAt') == validated[record['archiveDigest']][1], 'invalid-protected-status')
    require(re.fullmatch(r'export-\d{8}T\d{12}Z-[a-f0-9]{8}', es['success'].get('export', '')),
            'invalid-protected-export')
    cipher = backup.read_regular(WORK / 'cipher.age', 131072, 0o600)
    require(backup.digest(cipher) == es['success'].get('cipherDigest'), 'invalid-protected-ciphertext')


def restore():
    validate_workspace()
    pause()
    with backup.locked(backup.STORE), backup.locked(EXPORTS):
        for path in backup.STORE.glob('backup-*'):
            backup.private_directory(path)
            shutil.rmtree(path)
        for path in (WORK / 'backups').glob('backup-*'):
            shutil.copytree(path, backup.STORE / path.name)
        record = read_json(WORK / 'export-status.json')
        target = EXPORTS / record['success']['export'] / 'snapshot.tar.age'
        target.parent.mkdir(mode=0o700, exist_ok=True)
        target.write_bytes(backup.read_regular(WORK / 'cipher.age', 131072, 0o600))
        target.chmod(0o600)
        atomic_json(ES, record)
        atomic_json(BS, read_json(WORK / 'backup-status.json'))
        RECIPIENT.chmod(0o600)
    ctl('start', 'pink-party-backup.timer', 'pink-party-export.timer')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', choices=['initialize', 'check', 'restore', 'missing', 'stale', 'failed-export', 'corrupt', 'truncated'])
    parser.add_argument('--work-name', default='batch10-export-faults')
    args = parser.parse_args()
    require(os.geteuid() == 0, 'run-as-root')
    global WORK
    require(re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}', args.work_name), 'invalid-work-name')
    WORK = backup.RESTORES / args.work_name
    os.umask(0o077)
    if args.case == 'initialize':
        require(not WORK.exists(), 'use-new-workspace')
        pause()
        WORK.mkdir(mode=0o700)
        shutil.copytree(backup.STORE, WORK / 'backups')
        atomic_json(WORK / 'backup-status.json', read_json(BS))
        record = read_json(ES)
        atomic_json(WORK / 'export-status.json', record)
        backup.write_private(WORK / 'cipher.age', backup.read_regular(
            EXPORTS / record['success']['export'] / 'snapshot.tar.age', 131072, 0o600))
        validate_workspace()
        ctl('start', 'pink-party-backup.timer', 'pink-party-export.timer')
    elif args.case == 'check':
        validate_workspace()
    elif args.case == 'restore':
        restore()
    else:
        validate_workspace()
        pause()
        if args.case in ['missing', 'stale']:
            with backup.locked(backup.STORE):
                for path in backup.STORE.glob('backup-*'):
                    shutil.rmtree(path)
                if args.case == 'stale':
                    source = next((WORK / 'backups').glob('backup-*'))
                    target = backup.STORE / 'backup-20000101T000000000000Z-00000000'
                    shutil.copytree(source, target)
                    captured = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=1800)).isoformat()
                    output = io.BytesIO()
                    with tarfile.open(source / 'snapshot.tar', 'r:') as original, tarfile.open(fileobj=output, mode='w', format=tarfile.USTAR_FORMAT) as changed:
                        for member in original:
                            data = original.extractfile(member).read()
                            if member.name == 'manifest.json':
                                manifest = json.loads(data); manifest['capturedAt'] = captured
                                data = json.dumps(manifest).encode()
                            member.size = len(data)
                            changed.addfile(member, io.BytesIO(data))
                    (target / 'snapshot.tar').write_bytes(output.getvalue())
                    digest = backup.digest(output.getvalue())
                    (target / 'sha256').write_text(digest + '\n')
                    backup.validate_backup(target)
                    state = read_json(BS)
                    state['success'].update(snapshot=target.name, capturedAt=captured, archiveDigest=digest)
                    atomic_json(BS, state)
            ctl('start', 'pink-party-export.timer')
        elif args.case == 'failed-export':
            RECIPIENT.chmod(0o000)
            # A real new normal scheduled capture prevents the unchanged-capture fast path.
            ctl('start', 'pink-party-backup.timer', 'pink-party-export.timer')
        else:
            # Preserve coherent transport metadata so age, rather than just a hash, rejects the fault.
            state = read_json(ES)
            target = EXPORTS / state['success']['export'] / 'snapshot.tar.age'
            raw = target.read_bytes()
            raw = raw[:-1] if args.case == 'truncated' else raw[:-1] + bytes([raw[-1] ^ 1])
            target.write_bytes(raw)
            state['success']['cipherDigest'] = backup.digest(raw)
            atomic_json(ES, state)
        atomic_json(WORK / 'injected.json', {'case': args.case, 'at': now(), 'syntheticFault': True})
    print('Source export exercise: ' + args.case)


if __name__ == '__main__': main()

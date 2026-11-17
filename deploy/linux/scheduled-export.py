#!/usr/bin/env python3
"""Export the newest completed capture, or offer ciphertext and private job records."""

import base64
import importlib.util
import json
from pathlib import Path
import sys
from freshness import backup, run_job, read_state, check_state, age, now, instant, require, Fault, CAPTURE_MAX

spec = importlib.util.spec_from_file_location('encrypted', Path(__file__).with_name('encrypted-backup.py'))
encrypted = importlib.util.module_from_spec(spec)
spec.loader.exec_module(encrypted)
STORE = Path('/var/lib/pink-party-rolling-exports')
STATUS = Path('/var/lib/pink-party-export-status')
BACKUP_STATUS = Path('/var/lib/pink-party-backup-status')
RECIPIENT = Path('/var/lib/pink-party-export-config/recipient.txt')


def export(previous, snapshots=backup.STORE, store=STORE, recipient=RECIPIENT, status=BACKUP_STATUS):
    with backup.locked(snapshots), backup.locked(store):
        captures = [p for p in snapshots.iterdir() if backup.NAME.fullmatch(p.name)]
        require(0 < len(captures) <= backup.KEEP, 'missing-or-full-backups')
        # Validate bounded completed captures while the same lock blocks snapshot pruning.
        validated = [(p, backup.validate_backup(p)[1]) for p in captures]
        source, manifest = max(validated, key=lambda item: instant(item[1]['capturedAt']))
        at = now()
        age(manifest['capturedAt'], at, CAPTURE_MAX)
        capture = check_state(read_state(status), at, CAPTURE_MAX)
        require(capture['capturedAt'] == manifest['capturedAt'], 'backup-state-mismatch')
        digest = backup.digest(backup.read_regular(source / 'snapshot.tar', backup.ARCHIVE_LIMIT, 0o600))
        require(capture['archiveDigest'] == digest, 'backup-state-mismatch')
        completed = [p for p in store.iterdir() if encrypted.EXPORT_NAME.fullmatch(p.name)]
        require(len(completed) <= encrypted.KEEP, 'exports-full')
        if previous:
            require(instant(manifest['capturedAt']) >= instant(previous['capturedAt']), 'capture-rollback')
            if previous['archiveDigest'] == digest:
                cipher = backup.read_regular(store / previous['export'] / 'snapshot.tar.age', encrypted.CIPHER_LIMIT, 0o600)
                require(backup.digest(cipher) == previous['cipherDigest'], 'export-changed')
                return previous, 'unchanged'
        target = encrypted.export_locked(source, store, recipient)
        cipher = backup.read_regular(target / 'snapshot.tar.age', encrypted.CIPHER_LIMIT, 0o600)
        return dict(export=target.name, capturedAt=manifest['capturedAt'], archiveDigest=digest,
                    cipherDigest=backup.digest(cipher), exportedAt=now()), 'exported'


def offer():
    # Do not run the exporter on demand. Collection observes the independent scheduled jobs.
    with backup.locked(STATUS), backup.locked(STORE):
        state = read_state(STATUS)
        source = {'observedAt': now(), 'backup': read_state(BACKUP_STATUS), 'export': state}
        success = state['success'] if state else None
        cipher = None
        if success:
            require(encrypted.EXPORT_NAME.fullmatch(success['export']), 'state-invalid')
            cipher = backup.read_regular(STORE / success['export'] / 'snapshot.tar.age', encrypted.CIPHER_LIMIT, 0o600)
            require(backup.digest(cipher) == success['cipherDigest'], 'export-changed')
        return {'source': source, 'ciphertext': base64.b64encode(cipher).decode() if cipher else None}


if __name__ == '__main__':
    try:
        require(len(sys.argv) == 2 and sys.argv[1] in ['run', 'offer', 'inspect'], 'invalid-command')
        if sys.argv[1] == 'run':
            state = run_job(STATUS, export)
            print(json.dumps({'result': state['reason']}))
        elif sys.argv[1] == 'offer':
            print(json.dumps(offer(), separators=(',', ':')))
        else:
            print(json.dumps({'backup': read_state(BACKUP_STATUS), 'export': read_state(STATUS)}))
    except (OSError, ValueError, KeyError, TypeError):
        print('Scheduled export unavailable; inspect private status.', file=sys.stderr)
        sys.exit(1)

#!/usr/bin/env python3
"""Record attempts separately from successful scheduled snapshot captures."""

import json
from pathlib import Path
import subprocess
import sys
from freshness import backup, run_job, Fault


def capture(previous):
    path, manifest = backup.create_backup()
    return {'snapshot': path.name, 'capturedAt': manifest['capturedAt'],
            'archiveDigest': backup.digest(backup.read_regular(path / 'snapshot.tar', backup.ARCHIVE_LIMIT, 0o600))}, 'captured'


if __name__ == '__main__':
    try:
        state = run_job(Path('/var/lib/pink-party-backup-status'), capture)
        print(json.dumps({'result': state['reason']}))
    except (OSError, ValueError, subprocess.SubprocessError):
        print('Scheduled backup failed; inspect private status.', file=sys.stderr)
        sys.exit(1)

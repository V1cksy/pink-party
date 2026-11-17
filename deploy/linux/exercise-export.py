#!/usr/bin/env python3
"""Capture and encrypt a synthetic scheduled backup, then restore normal source state."""

import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

from backup import (SOURCES, STORE, RESTORES, MODES, read_regular, write_private,
                    validate_backup, require)

APP = Path('/opt/pink-party/app')
NODE = '/opt/pink-party/node/bin/node'
UNITS = ['pink-party.service', 'pink-party-monitor.timer', 'pink-party-backup.timer']


def main():
    require(os.geteuid() == 0 and sys.platform == 'linux', 'Run as root in Linux')
    recipient = Path(sys.argv[1])
    os.umask(0o077)
    lock = Path('/run/pink-party-verification.lock')
    lock.mkdir(mode=0o700)
    work = RESTORES / ('export-exercise-' + uuid.uuid4().hex[:12])
    work.mkdir(mode=0o700)
    report = {'scope': 'Codex-run assisted scheduled encrypted export',
              'startedAt': dt.datetime.now(dt.timezone.utc).isoformat()}
    original = {name: read_regular(path, 16384, MODES[name]) for name, path in SOURCES.items()}
    for name, data in original.items():
        write_private(work / ('original-session.json' if name.startswith('data') else 'original.env'), data)
    log = open(work / 'commands.log', 'xb')

    def command(args):
        result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=40)
        log.write(result.stdout)
        log.flush()
        require(result.returncode == 0, 'Exercise command failed; inspect private log')
        return result.stdout

    def ctl(*args):
        return command(['systemctl', *args])

    def healthy():
        return subprocess.run([NODE, str(APP / 'deploy/linux/service-health.ts')],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5).returncode == 0

    def until(read):
        deadline = time.monotonic() + 75
        while time.monotonic() < deadline:
            value = read()
            if value:
                return value
            time.sleep(0.25)
        raise ValueError('Exercise wait expired')

    def replace(data):
        temporary = SOURCES['data/session.json'].with_suffix('.export-stage')
        write_private(temporary, data, 0o644)
        os.replace(temporary, SOURCES['data/session.json'])

    def scheduled(expected, before):
        for path in sorted(STORE.glob('backup-*'), reverse=True):
            if path.name not in before and validate_backup(path)[0] == expected:
                return path

    try:
        ctl('stop', 'pink-party-backup.timer', 'pink-party-backup.service')
        synthetic = json.loads(original['data/session.json'])
        synthetic['title'] = 'Synthetic batch 8: recovered from the off-VM vault.'
        data = (json.dumps(synthetic, indent=2) + '\n').encode()
        replace(data)
        ctl('restart', 'pink-party.service')
        until(healthy)
        before = {p.name for p in STORE.glob('backup-*')}
        started = time.monotonic()
        ctl('start', 'pink-party-backup.timer')
        expected = {**original, 'data/session.json': data}
        capture = until(lambda: scheduled(expected, before))
        report['scheduledCaptureWaitMs'] = round((time.monotonic() - started) * 1000)
        report['capturedAt'] = validate_backup(capture)[1]['capturedAt']
        ctl('stop', 'pink-party-backup.timer', 'pink-party-backup.service')
        # Keep this actual scheduled capture beyond ordinary seven-copy pruning.
        import shutil
        protected = work / 'scheduled-backup'
        shutil.copytree(capture, protected)
        started = time.monotonic()
        output = command(['python3', '-B', str(APP / 'deploy/linux/encrypted-backup.py'),
                          'export', str(capture), '/var/lib/pink-party-exports',
                          '--recipient-file', str(recipient)])
        report['exportMs'] = round((time.monotonic() - started) * 1000)
        report['exportResult'] = json.loads(output)
        report['passed'] = True
    finally:
        ctl('stop', 'pink-party-backup.timer', 'pink-party-backup.service')
        replace(original['data/session.json'])
        require(read_regular(SOURCES['private/pink-party.env'], 16384, 0o600) == original['private/pink-party.env'],
                'Source credentials changed')
        ctl('restart', 'pink-party.service')
        until(healthy)
        before = {p.name for p in STORE.glob('backup-*')}
        normal_after = dt.datetime.now(dt.timezone.utc).isoformat()
        ctl('start', 'pink-party-monitor.timer', 'pink-party-backup.timer')
        until(lambda: scheduled(original, before))
        until(lambda: any(row['observedAt'] > normal_after and row['status'] == 'up'
                          for row in json.loads(Path('/var/lib/pink-party-monitor/history.json').read_text())))
        report['normalSourceAndCredentialsRestored'] = True
        report['freshNormalScheduledBackupAndMonitoring'] = True
        write_private(work / 'report.json', (json.dumps(report, indent=2) + '\n').encode())
        log.close()
        lock.rmdir()
    print(json.dumps(report))


if __name__ == '__main__':
    main()

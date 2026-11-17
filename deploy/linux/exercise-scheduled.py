#!/usr/bin/env python3
"""Begin/finish a sequential synthetic scheduled-export exercise in the existing local lab."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import time
import re
from freshness import backup, atomic_json, now, read_json, require

WORK = Path('/var/lib/pink-party-restores/batch10-chain')
LOCK = Path('/run/pink-party-verification.lock')
APP = Path('/opt/pink-party/app')
TIMERS = ['pink-party-backup.timer', 'pink-party-export.timer']


def ctl(*args):
    subprocess.run(['systemctl', *args], check=True, timeout=15,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def wait(read, seconds=100):
    end = time.monotonic() + seconds
    while time.monotonic() < end:
        value = read()
        if value:
            return value
        time.sleep(0.25)
    raise RuntimeError('Scheduled exercise wait expired')


def healthy():
    return subprocess.run(['/opt/pink-party/node/bin/node', str(APP / 'deploy/linux/service-health.ts')],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5).returncode == 0


def replace_session(data):
    path = backup.SOURCES['data/session.json']
    stage = path.with_suffix('.chain-stage')
    backup.write_private(stage, data, 0o644)
    os.replace(stage, path)


def scheduled_capture(expected, after):
    for path in backup.STORE.glob('backup-*'):
        payload, manifest = backup.validate_backup(path)
        if manifest['capturedAt'] > after and payload['data/session.json'] == expected:
            return path, manifest


def begin(marker='Synthetic batch 10: automatically collected encrypted recovery.'):
    require(not WORK.exists() and not LOCK.exists(), 'use-new-workspace-and-inspect-existing-lock')
    require(healthy(), 'healthy-baseline-required')
    LOCK.mkdir(mode=0o700)
    WORK.mkdir(mode=0o700)
    ctl('stop', *TIMERS, 'pink-party-backup.service', 'pink-party-export.service')
    original = {name: backup.read_regular(path, backup.LIMIT, backup.MODES[name])
                for name, path in backup.SOURCES.items()}
    backup.write_private(WORK / 'original-session.json', original['data/session.json'])
    backup.write_private(WORK / 'original.env', original['private/pink-party.env'])
    report = {'startedAt': now(), 'scope': 'Actual scheduled capture and export; Mac collection observed separately'}
    # finish can restore from this journal even if restart/readiness fails after the data change.
    atomic_json(WORK / 'report.json', report)
    synthetic = json.loads(original['data/session.json'])
    synthetic['title'] = marker
    data = (json.dumps(synthetic, indent=2) + '\n').encode()
    backup.write_private(WORK / 'synthetic-session.json', data)
    replace_session(data)
    ctl('restart', 'pink-party.service')
    wait(healthy)
    tick = time.monotonic()
    ctl('enable', '--now', 'pink-party-export.timer')
    ctl('start', 'pink-party-backup.timer', 'pink-party-monitor.timer')
    path, manifest = wait(lambda: scheduled_capture(data, report['startedAt']))
    import shutil
    shutil.copytree(path, WORK / 'scheduled-capture')
    report.update(capturedAt=manifest['capturedAt'], scheduledCaptureWaitMs=round((time.monotonic()-tick)*1000))
    atomic_json(WORK / 'report.json', report)
    print(json.dumps(report))


def finish():
    report = read_json(WORK / 'report.json')
    ctl('stop', *TIMERS, 'pink-party-backup.service', 'pink-party-export.service')
    original = backup.read_regular(WORK / 'original-session.json', backup.LIMIT, 0o600)
    require(backup.read_regular(WORK / 'original.env', backup.LIMIT, 0o600) ==
            backup.read_regular(backup.SOURCES['private/pink-party.env'], backup.LIMIT, 0o600), 'credentials-changed')
    replace_session(original)
    ctl('restart', 'pink-party.service')
    wait(healthy)
    after = now()
    ctl('start', *TIMERS, 'pink-party-monitor.timer')
    _, manifest = wait(lambda: scheduled_capture(original, after))
    wait(lambda: any(row['observedAt'] > after and row['status'] == 'up'
                    for row in json.loads(Path('/var/lib/pink-party-monitor/history.json').read_text())))
    report.update(originalDataAndConfigurationRestored=True, freshNormalCaptureAt=manifest['capturedAt'],
                  freshNormalScheduledMonitoring=True, restoredAt=now())
    atomic_json(WORK / 'report.json', report)
    LOCK.rmdir()
    print(json.dumps(report))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['begin', 'finish'])
    parser.add_argument('--work-name', default='batch10-chain')
    parser.add_argument('--batch11', action='store_true')
    args = parser.parse_args()
    require(os.geteuid() == 0, 'run-as-root')
    require(re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_-]{0,63}', args.work_name), 'invalid-work-name')
    WORK = backup.RESTORES / args.work_name
    os.umask(0o077)
    if args.command == 'finish':
        finish()
    elif args.batch11:
        begin('Synthetic batch 11: recovered from off-device storage.')
    else:
        begin()

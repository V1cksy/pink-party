#!/usr/bin/env python3
"""Compare a fresh local deployment with validated recovered files, without printing secrets."""

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import time
import urllib.request

from backup import (SOURCES, STORE, MODES, read_regular, private_directory,
                    require, validate_backup, write_private)


def verify(recovered, marker):
    private_directory(recovered)
    expected = {name: read_regular(recovered / name, 16384, MODES[name]) for name in MODES}
    require(all(read_regular(SOURCES[name], 16384, MODES[name]) == value
                for name, value in expected.items()), 'Recovered installed content mismatch')
    fields = dict(line.split('=', 1) for line in expected['private/pink-party.env'].decode().splitlines())
    require(fields['PINK_PARTY_MODE'] == 'local', 'Recovery verifier requires local mode')
    service = subprocess.check_output(['systemctl', 'show', 'pink-party.service',
                                       '--property=MainPID', '--value'], timeout=5).decode().strip()
    require(int(service) > 0, 'Service is not running')
    process_env = dict(item.split(b'=', 1) for item in Path('/proc/' + service + '/environ').read_bytes().split(b'\0') if b'=' in item)
    require(all(process_env.get(key.encode()) == value.encode() for key, value in fields.items()),
            'Recovered credentials are not loaded by service')
    subprocess.run(['/opt/pink-party/node/bin/node', '/opt/pink-party/app/deploy/linux/service-health.ts'],
                   check=True, timeout=5, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    with urllib.request.urlopen('http://127.0.0.1:3000/api/session', timeout=3) as response:
        require(json.load(response) == json.loads(expected['data/session.json']), 'Served session mismatch')
    require(json.loads(expected['data/session.json'])['title'] ==
            marker, 'Recovery marker missing')
    for unit in ['pink-party.service', 'pink-party-monitor.timer', 'pink-party-backup.timer']:
        for command in ['is-enabled', 'is-active']:
            subprocess.run(['systemctl', command, '--quiet', unit], check=True, timeout=5)
    after = dt.datetime.now(dt.timezone.utc).isoformat()
    # Do not start oneshots to manufacture scheduled evidence. Observe the normal timers.
    before = {p.name for p in STORE.glob('backup-*')}
    subprocess.run(['systemctl', 'restart', 'pink-party-backup.timer'], check=True, timeout=5)
    start = time.monotonic()
    deadline = start + 75
    scheduled = None
    monitoring = None
    while time.monotonic() < deadline:
        if not scheduled:
            for path in STORE.glob('backup-*'):
                if path.name not in before:
                    payloads, manifest = validate_backup(path)
                    if payloads == expected:
                        scheduled = manifest['capturedAt']
        history_path = Path('/var/lib/pink-party-monitor/history.json')
        history = json.loads(history_path.read_text()) if history_path.exists() else []
        monitoring = next((row['observedAt'] for row in history
                           if row['observedAt'] > after and row['status'] == 'up'), None)
        if scheduled and monitoring:
            break
        time.sleep(0.5)
    require(scheduled and monitoring, 'Fresh scheduled recovery evidence missing')
    return {'scope': 'Automated fresh local Ubuntu VM recovery',
            'exactInstalledBytesOwnerAndModes': True, 'recoveredEnvironmentLoadedByService': True,
            'ownedWebControlHealth': True, 'servedRecoveryMarker': True,
            'appAndTimersEnabledAndActive': True, 'freshScheduledBackupAt': scheduled,
            'freshScheduledMonitoringAt': monitoring, 'observedScheduledEvidenceMs': round((time.monotonic() - start) * 1000),
            'media': 'Run the separate browser suite; HTTP health does not establish reception'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('recovered', type=Path)
    parser.add_argument('report', type=Path)
    parser.add_argument('--marker', default='Synthetic batch 8: recovered from the off-VM vault.')
    args = parser.parse_args()
    require(os.geteuid() == 0, 'Run as root in recovery guest')
    os.umask(0o077)
    report = verify(args.recovered, args.marker)
    write_private(args.report, (json.dumps(report, indent=2) + '\n').encode())
    print('Exact recovered files, loaded credentials, served marker and scheduled jobs verified.')


if __name__ == '__main__':
    main()

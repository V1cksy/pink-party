#!/usr/bin/env bash
set -euo pipefail
umask 077
[[ $(id -u) == 0 && $(uname -m) == aarch64 ]]
app=/opt/pink-party/app
export PATH=/opt/pink-party/node/bin:/opt/pink-party/bin:/usr/bin:/bin
# No cloud/API credentials are needed on the host for these checks.
PYTHONPATH="$app/deploy/linux" python3 -B - <<'PY'
import datetime as dt
import json
import os
from pathlib import Path
import re
import subprocess
import time
import urllib.request
import uuid
from backup import (STORE, RESTORES, SOURCES, MODES, read_regular, require,
                    restore_backup, validate_backup)

def run(*args):
    return subprocess.run(args, capture_output=True, text=True, timeout=20, check=True).stdout

env = read_regular(SOURCES['private/pink-party.env'], 16384, 0o600)
require(b'PUBLIC_ORIGIN=' in env and b'INVITED_LOGINS=' in env, 'Private configuration required')
status = json.loads(run('tailscale', 'status', '--json'))
require(status['BackendState'] == 'Running' and status['Self']['Online'], 'Connected native Tailscale required')
ip = next(x for x in status['Self']['TailscaleIPs'] if '.' in x)
require(ip in run('ip', '-4', 'addr', 'show', 'dev', 'tailscale0'), 'Native private interface required')
group = run('systemctl', 'show', 'pink-party.service', '-p', 'ControlGroup', '--value').strip()
for port, flag, address in [(3000, '-ltnp', '127.0.0.1'), (7880, '-ltnp', '127.0.0.1'), (7882, '-lunp', ip)]:
    sockets = run('ss', '-H', flag, f'sport = :{port}').splitlines()
    require(len(sockets) == 1 and sockets[0].split()[3] == f'{address}:{port}', 'Unexpected application socket address')
    pids = set(re.findall(r'pid=(\d+)', sockets[0]))
    require(len(pids) == 1, 'Unexpected application socket ownership')
    require(f'0::{group}' in Path('/proc/' + pids.pop() + '/cgroup').read_text().splitlines(), 'Foreign application socket rejected')
run('/opt/pink-party/node/bin/node', '/opt/pink-party/app/deploy/linux/service-health.ts')
report = {'scope': 'Automated Linux private-host checks; not media or human listening',
          'checkedAt': dt.datetime.now(dt.timezone.utc).isoformat(),
          'nativePrivateInterface': True, 'exactOwnedAppControlMediaSockets': True,
          'ownedHealth': True, 'media': 'not-tested'}
deadline = time.monotonic() + 75
source = {name: read_regular(path, 16384, MODES[name]) for name, path in SOURCES.items()}
while True:
    candidates = sorted(STORE.glob('backup-*'), reverse=True)
    match = next(((path, manifest) for path in candidates
                  for payload, manifest in [validate_backup(path)] if payload == source), None)
    if match:
        break
    require(time.monotonic() < deadline, 'No matching scheduled private backup; inspect timer and job')
    time.sleep(0.5)
archive, manifest = match
destination = RESTORES / ('private-check-' + uuid.uuid4().hex[:12])
started = time.monotonic()
restore_backup(archive, destination)
for name, data in source.items():
    require(read_regular(destination / name, 16384, MODES[name]) == data, 'Separate restore mismatch')
require(read_regular(SOURCES['private/pink-party.env'], 16384, 0o600) == env, 'Working credentials changed')
report['scheduledPrivateBackupCapturedAt'] = manifest['capturedAt']
report['separateRestoreMs'] = round((time.monotonic() - started) * 1000)
report['separateRestoreHashesAndModes'] = True
report['workingCredentialsPreserved'] = True
report['sameDiskBackup'] = True
report['passed'] = True
path = RESTORES / 'private-validation.json'
path.write_text(json.dumps(report, indent=2) + '\n')
path.chmod(0o600)
print(json.dumps(report))
PY
# This deliberate stop runs only after checks and with all browser clients closed.
node --env-file=/etc/pink-party/pink-party.env "$app/deploy/linux/incident.ts"

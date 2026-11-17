#!/usr/bin/env python3
"""Stop a project VM; allow stale Lima cleanup only after a new VZ stopped event."""

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import signal
import subprocess
import time


def stop(vm):
    log = Path.home() / '.lima' / vm / 'ha.stderr.log'
    offset = log.stat().st_size
    requested = dt.datetime.now(dt.timezone.utc)

    def command(args, seconds):
        try:
            return subprocess.run(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                  timeout=seconds).returncode
        except subprocess.TimeoutExpired:
            return None

    normal = command(['limactl', 'stop', vm], 35)

    def stopped_event():
        with log.open() as stream:
            stream.seek(offset)
            for line in stream:
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if row.get('msg') == '[VZ] - vm state change: stopped' and dt.datetime.fromisoformat(row['time']) >= requested.replace(microsecond=0):
                    return row['time']

    event = stopped_event()
    if normal != 0 and not event:
        command(['limactl', 'shell', '--workdir=/tmp', vm, 'sudo', 'poweroff'], 10)
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline and not event:
            time.sleep(0.5)
            event = stopped_event()
    if not event:
        raise RuntimeError('No new VZ stopped event; refusing force cleanup. Inspect guest state privately.')
    if normal != 0:
        if command(['limactl', 'stop', '--force', vm], 15) != 0:
            raise RuntimeError('VZ stopped, but stale Lima cleanup needs private inspection.')
    state = json.loads(subprocess.check_output(['limactl', 'list', vm, '--json'], timeout=5))
    if state['status'] != 'Stopped':
        raise RuntimeError('Guest poweroff observed but Lima state is not Stopped.')
    # Some VZ shutdowns leave a hostagent after the VM is already stopped. Target only this VM.
    processes = subprocess.check_output(['ps', '-axo', 'pid=,command='], timeout=5).decode().splitlines()
    marker = str(Path.home() / '.lima' / vm / 'ha.pid')
    for row in processes:
        fields = row.strip().split(None, 1)
        if len(fields) != 2 or 'limactl hostagent --pidfile ' + marker + ' ' not in fields[1]:
            continue
        pid = int(fields[0])
        os.kill(pid, signal.SIGTERM)
        time.sleep(2)
        current = subprocess.run(['ps', '-p', str(pid), '-o', 'command='], capture_output=True, timeout=5).stdout.decode()
        if 'limactl hostagent --pidfile ' + marker + ' ' in current:
            os.kill(pid, signal.SIGKILL)
    return {'normalStopExit': normal, 'newVzStoppedAt': event, 'status': 'Stopped',
            'forceCleanupOnlyAfterCurrentVzStop': normal != 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('vm', choices=['pink-party', 'pink-party-recovery-b8'])
    args = parser.parse_args()
    print(json.dumps(stop(args.vm)))


if __name__ == '__main__':
    main()

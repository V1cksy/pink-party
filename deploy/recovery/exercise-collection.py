#!/usr/bin/env python3
"""Observe scheduled collection failures with disposable references and protected originals."""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import collector as c


def wait(read, seconds=100):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = read()
        if value:
            return value
        time.sleep(0.01)
    raise RuntimeError('Scheduled collection observation expired')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('config', type=Path)
    parser.add_argument('evidence', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    c.backup.private_directory(args.evidence)
    original = c.read_json(args.config)
    config = c.configuration(args.config)
    c.require(c.inspect(config)['healthy'], 'healthy-scheduled-baseline-required')
    original_copies = {p.name: p.read_bytes() for p in config['store'].glob('*.age')}
    report = {'startedAt': c.now(), 'scope': 'Actual launchd invocations; temporary local input faults', 'observations': []}

    def unchanged():
        for name, data in original_copies.items():
            c.require((config['store'] / name).read_bytes() == data, 'good-copy-changed')

    def observed(label, outcome, after):
        tick = time.monotonic()
        def read():
            state = c.read_state(config['state'])
            if state and state['attemptedAt'] > after and state['outcome'] == outcome:
                return state
        state = wait(read)
        health = c.inspect(c.configuration(args.config))
        report['observations'].append({'case': label, 'outcome': state['outcome'], 'reason': state['reason'],
            'attemptedAt': state['attemptedAt'], 'finishedAt': state['finishedAt'],
            'waitMs': round((time.monotonic()-tick)*1000), 'healthy': health['healthy']})
        c.atomic_json(args.evidence / 'collection-exercise.json', report)
        unchanged()
        return state

    def fault(label, updates):
        after = c.now()
        c.atomic_json(args.config, {**original, **updates})
        observed(label, 'error', after)
        after = c.now()
        c.atomic_json(args.config, original)
        observed(label + '-scheduled-recovery', 'success', after)

    keys = config['state'].parent / 'temporary-exercise-keys'
    keys.mkdir(mode=0o700)
    wrong = keys / 'wrong.agekey'
    subprocess.run(['age-keygen', '-o', str(wrong)], check=True, stderr=subprocess.DEVNULL, timeout=5)
    wrong.chmod(0o600)
    full = config['state'].parent / 'temporary-full-rolling'
    full_state = config['state'].parent / 'temporary-full-state'
    try:
        fault('wrong-temporary-key', {'identity': str(wrong)})
        fault('missing-temporary-key', {'identity': str(keys / 'missing.agekey')})
        wrong.chmod(0o000)
        fault('unavailable-temporary-key', {'identity': str(wrong)})
        wrong.chmod(0o600)
        c.initialize({**config, 'store': full, 'state': full_state})
        for i in range(8):
            c.backup.write_private(full / ('export-20200101T000000000000Z-%08x.age' % i), b'Synthetic capacity fixture')
        fault('full-separate-rolling-area', {'store': str(full)})
        c.require(len(list(full.glob('*.age'))) == 8, 'full-area-pruned')

        # Catch a real scheduled transfer after staging opens, without replacing limactl/age.
        runtime = Path.home() / 'Library/Application Support/PinkPartyAutomation/runtime/deploy/recovery/collector.py'
        def transferring():
            if not list(config['store'].glob('.collect-*/offer.json')):
                return None
            rows = subprocess.check_output(['ps', '-axo', 'pid=,command='], timeout=3).decode().splitlines()
            for row in rows:
                fields = row.strip().split(None, 1)
                if len(fields) == 2 and str(runtime) + ' worker ' + str(args.config) in fields[1]:
                    return int(fields[0])
        pid = wait(transferring)
        os.killpg(pid, signal.SIGSTOP)
        try:
            state = c.read_state(config['state'])
            c.require(state['outcome'] == 'running', 'interruption-window-missed')
            stages = list(config['store'].glob('.collect-*/offer.json'))
            size = stages[0].stat().st_size if stages else None
            overlap = subprocess.run([sys.executable, '-B', str(runtime), 'worker', str(args.config)],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=5)
            c.require(overlap.returncode != 0, 'overlap-was-not-rejected')
            report['observations'].append({'case': 'actual-transfer-process-stop-and-overlap',
                'outcome': 'running', 'overlapRejected': True, 'responseBytesAtStop': size,
                'healthy': c.inspect(config)['healthy']})
        finally:
            os.killpg(pid, signal.SIGKILL)
        unchanged()
        after = c.now()
        observed('interrupted-transfer-scheduled-recovery', 'success', after)
        c.require(not list(config['store'].glob('.collect-*')) and not list(config['state'].glob('.verify-*')),
                  'interrupted-staging-remains')

        # Corrupt state is retained, rather than silently manufacturing a new successful history.
        good_state = c.read_json(config['state'] / 'status.json')
        with c.backup.locked(config['state']):
            c.atomic_json(config['state'] / 'status.json', {'synthetic': 'corrupt-state'})
        before = time.monotonic()
        wait(lambda: not c.inspect(config)['healthy'])
        # Give the 15-second exercise schedule a real chance to try the corrupt record.
        time.sleep(18)
        c.require(c.read_json(config['state'] / 'status.json') == {'synthetic': 'corrupt-state'}, 'corrupt-state-overwritten')
        report['observations'].append({'case': 'corrupt-state-retained', 'healthy': False,
                                     'observedMs': round((time.monotonic()-before)*1000)})
        with c.backup.locked(config['state']):
            c.atomic_json(config['state'] / 'status.json', good_state)
        observed('corrupt-state-scheduled-recovery', 'success', c.now())
        report.update(completedAt=c.now(), originalGoodCopiesUnchanged=True, workingIdentityNeverModified=True)
    finally:
        c.atomic_json(args.config, original)
        wrong.chmod(0o600)
        import shutil
        shutil.rmtree(keys)
        for path in [full, full_state]:
            if path.exists(): shutil.rmtree(path)
        c.atomic_json(args.evidence / 'collection-exercise.json', report)
    print('Scheduled collection failure and recovery observations saved privately.')


if __name__ == '__main__': main()

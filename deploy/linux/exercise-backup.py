#!/usr/bin/env python3
"""Sequential, disruptive backup/recovery exercise for the local Linux lab."""

import datetime as dt
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import urllib.request
import uuid

from backup import (MODES, RESTORES, SOURCES, STORE, create_backup, digest,
                    locked, private_directory, read_regular, require,
                    restore_backup, validate_backup, write_private)

APP = Path('/opt/pink-party/app')
NODE = '/opt/pink-party/node/bin/node'
SERVICE = 'pink-party.service'
TIMER = 'pink-party-backup.timer'
MONITOR = 'pink-party-monitor.timer'
LOCK = Path('/run/pink-party-verification.lock')


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def until(read, label, seconds=75):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        value = read()
        if value:
            return value
        time.sleep(0.25)
    raise ValueError('Timed out: ' + label)


def main():
    require(os.geteuid() == 0 and sys.platform == 'linux', 'Run as root in Linux')
    os.umask(0o077)
    private_directory(RESTORES)
    LOCK.mkdir(mode=0o700)
    work = RESTORES / ('exercise-' + uuid.uuid4().hex[:12])
    work.mkdir(mode=0o700)
    log = open(work / 'commands.log', 'xb')
    report = {'scope': 'Codex-run assisted local Linux synthetic-data recovery', 'startedAt': now()}
    changed = False
    original = None
    credentials = None

    def command(args, expected=True):
        result = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=40)
        log.write(result.stdout)
        log.flush()
        if expected:
            require(result.returncode == 0, 'Command failed; inspect private exercise log')
        return result

    def ctl(*args, expected=True):
        return command(['systemctl', *args], expected)

    def active(unit):
        return ctl('is-active', '--quiet', unit, expected=False).returncode == 0

    def health():
        return command([NODE, str(APP / 'deploy/linux/service-health.ts')], False).returncode == 0

    def session():
        with urllib.request.urlopen('http://127.0.0.1:3000/api/session', timeout=2) as response:
            return json.load(response)

    def replace_session(data):
        target = SOURCES['data/session.json']
        temp = target.with_suffix('.recovery-tmp')
        write_private(temp, data, MODES['data/session.json'])
        os.replace(temp, target)

    def check_session(data):
        expected = json.loads(data)
        require(session() == expected, 'Application did not serve expected restored data')

    def scheduled_up(after):
        history = json.loads(Path('/var/lib/pink-party-monitor/history.json').read_text())
        return next((row for row in history if row['observedAt'] > after and row['status'] == 'up'), None)

    try:
        require(health(), 'Application must start healthy')
        require(active(MONITOR) and active(TIMER), 'Both timers must start active')
        original = read_regular(SOURCES['data/session.json'], 16384, 0o644)
        credentials = read_regular(SOURCES['private/pink-party.env'], 16384, 0o600)
        write_private(work / 'original-session.json', original)
        write_private(work / 'original.env', credentials)
        changed = True
        ctl('stop', TIMER, 'pink-party-backup.service')
        synthetic = json.loads(original)
        synthetic['title'] = 'Backup exercise A: a synthetic evening on the farm.'
        snapshot_source = (json.dumps(synthetic, indent=2) + '\n').encode()
        replace_session(snapshot_source)
        ctl('restart', SERVICE)
        until(health, 'synthetic source health')
        check_session(snapshot_source)
        before = {p.name for p in STORE.glob('backup-*')}
        scheduled_start = now()
        ctl('start', TIMER)
        # Uses the normal timer's OnActiveSec; no manual backup service start or temporary cadence.
        def new_backup():
            candidates = sorted(p for p in STORE.glob('backup-*') if p.name not in before)
            if not candidates:
                return None
            candidate = candidates[-1]
            payloads, manifest = validate_backup(candidate)
            require(payloads['data/session.json'] == snapshot_source
                    and payloads['private/pink-party.env'] == credentials, 'Scheduled capture differs')
            return candidate, manifest
        archive, manifest = until(new_backup, 'actual scheduled backup')
        report['scheduled'] = {'timerStartedAt': scheduled_start, 'capturedAt': manifest['capturedAt'],
                               'completedObservedAt': now(), 'sourceBytesMatched': True}
        ctl('stop', TIMER, 'pink-party-backup.service')
        journal = command(['journalctl', '--namespace=pink-party-backup', '-u', 'pink-party-backup.service',
                           '--since', scheduled_start, '-o', 'cat', '--no-pager']).stdout.decode()
        records = [json.loads(line) for line in journal.splitlines() if line.startswith('{')]
        completed = next(row for row in records if row.get('backup') == archive.name)
        report['scheduled']['jobDurationMs'] = completed['durationMs']
        restored = work / 'restored'
        start = time.monotonic()
        restore_backup(archive, restored)
        report['restoreToSeparateDirectoryMs'] = round((time.monotonic() - start) * 1000)
        require(read_regular(restored / 'data/session.json', 16384, 0o644) == snapshot_source, 'Session mismatch')
        require(read_regular(restored / 'private/pink-party.env', 16384, 0o600) == credentials, 'Config mismatch')
        # Use the actual application validators without printing either payload.
        command([NODE, '--env-file=' + str(restored / 'private/pink-party.env'), '--input-type=module', '-e',
                 "import {loadSettings} from './server/config.ts'; import {readSession} from './server/session.ts'; "
                 "loadSettings(process.env); await readSession(new URL('file://' + process.argv[1]));",
                 str(restored / 'data/session.json')])
        report['separateRestore'] = {'exactHashesAndModes': True, 'applicationValidatorsPassed': True,
                                    'workingCredentialsReplaced': False}

        # A rejected backup must leave all completed snapshots and the running application intact.
        prior = {p.name: digest((p / 'snapshot.tar').read_bytes()) for p in STORE.glob('backup-*')}
        pid = ctl('show', SERVICE, '-p', 'MainPID', '--value').stdout
        SOURCES['private/pink-party.env'].chmod(0o644)
        try:
            failed = ctl('start', 'pink-party-backup.service', expected=False)
            require(failed.returncode != 0, 'Unsafe source permissions were accepted')
        finally:
            SOURCES['private/pink-party.env'].chmod(0o600)
        failure_journal = command(['journalctl', '--namespace=pink-party-backup', '-u', 'pink-party-backup.service', '-n', '20', '-o', 'cat', '--no-pager']).stdout
        require(b'Input permission mismatch' in failure_journal, 'Backup permission diagnostic missing')
        require(ctl('show', 'pink-party-backup.service', '-p', 'Result', '--value').stdout.strip() == b'exit-code',
                'Backup unit failure missing')
        require(prior == {p.name: digest((p / 'snapshot.tar').read_bytes()) for p in STORE.glob('backup-*')},
                'Failed backup changed existing copies')
        require(health() and ctl('show', SERVICE, '-p', 'MainPID', '--value').stdout == pid,
                'Failed backup disturbed deployment')
        report['failedBackup'] = {'unsafeSourceModeRejected': True, 'unitResult': 'exit-code',
                                  'priorArchiveHashesUnchanged': True, 'runningServiceUnchanged': True,
                                  'reason': 'Input permission mismatch'}
        for kind in ['missing', 'corrupt']:
            bad = STORE / ('exercise-' + kind + '-' + uuid.uuid4().hex[:8])
            try:
                if kind == 'corrupt':
                    shutil.copytree(archive, bad)
                    with open(bad / 'snapshot.tar', 'ab') as stream:
                        stream.write(b'corrupt')
                try:
                    restore_backup(bad, work / kind)
                except (ValueError, OSError) as error:
                    expected_error = (kind == 'missing' and isinstance(error, FileNotFoundError)) or (
                        kind == 'corrupt' and isinstance(error, ValueError) and str(error) == 'Archive checksum mismatch')
                    require(expected_error, 'Wrong invalid-restore diagnostic')
                    log.write((type(error).__name__ + ': ' + ('Archive checksum mismatch' if kind == 'corrupt' else 'Missing backup input') + '\n').encode())
                    require(not (work / kind).exists(), 'Failed restore published a destination')
                else:
                    raise ValueError('Invalid restore was accepted')
            finally:
                if bad.exists():
                    shutil.rmtree(bad)
        require(health() and ctl('show', SERVICE, '-p', 'MainPID', '--value').stdout == pid,
                'Invalid restore disturbed the working deployment')
        require(read_regular(SOURCES['data/session.json'], 16384, 0o644) == snapshot_source
                and read_regular(SOURCES['private/pink-party.env'], 16384, 0o600) == credentials,
                'Invalid restore changed working files')
        require(prior == {p.name: digest((p / 'snapshot.tar').read_bytes()) for p in STORE.glob('backup-*')},
                'Invalid restore changed prior backup archives')
        report['invalidRestore'] = {'missingRejected': True, 'corruptRejected': True,
                                    'noDestinationPublished': True, 'workingDeploymentUnaffected': True,
                                    'sourceAndCredentialsUnchanged': True, 'priorArchiveHashesUnchanged': True,
                                    'missingReason': 'FileNotFoundError', 'corruptReason': 'Archive checksum mismatch'}
        with locked(STORE):
            try:
                create_backup()
            except ValueError as error:
                require(str(error) == 'Another backup or restore is running', 'Wrong overlap failure')
            else:
                raise ValueError('Overlapping backup accepted')
        report['overlapRejected'] = True

        synthetic['title'] = 'Backup exercise B: this later change will be lost.'
        changed_data = (json.dumps(synthetic, indent=2) + '\n').encode()
        replace_session(changed_data)
        ctl('restart', SERVICE)
        until(health, 'changed session health')
        check_session(changed_data)
        loss_at = now()
        ctl('stop', SERVICE)
        SOURCES['data/session.json'].unlink()
        ctl('start', SERVICE)
        time.sleep(1)
        require(not health(), 'Missing session incorrectly started healthy')
        raw = command(['journalctl', '-u', SERVICE, '--since', loss_at, '-o', 'cat', '--no-pager']).stdout
        require(b'ENOENT' in raw, 'Missing-session startup diagnostic absent')
        ctl('stop', SERVICE)
        require(active(MONITOR), 'Monitor stopped during data loss')
        recovery_start = now()
        start = time.monotonic()
        # Restore again from the retained archive; this is the recovery measured below.
        recovery = work / 'loss-recovery'
        restore_backup(archive, recovery)
        replace_session(read_regular(recovery / 'data/session.json', 16384, 0o644))
        ctl('reset-failed', SERVICE)
        ctl('start', SERVICE)
        until(health, 'restored application health')
        check_session(snapshot_source)
        report['lossRecovery'] = {'lossRequestedAt': loss_at, 'recoveryStartedAt': recovery_start,
                                  'applicationVerifiedAt': now(),
                                  'restoreThroughServedDataMs': round((time.monotonic() - start) * 1000),
                                  'changedDataServedBeforeLoss': True, 'missingDataPreventedStartup': True,
                                  'backupDataServedAfterRestore': True, 'monitorStayedActive': True}
        require(read_regular(SOURCES['private/pink-party.env'], 16384, 0o600) == credentials,
                'Working credentials changed')
        report['credentialsPreserved'] = True
        report['passed'] = True
    except Exception:
        report['passed'] = False
        import traceback
        log.write(traceback.format_exc().encode())
        log.flush()
        print('Exercise failed; inspect the private restore exercise directory.', file=sys.stderr)
    finally:
        cleanup_ok = False
        normal_data = False
        try:
            if changed:
                require(credentials == read_regular(SOURCES['private/pink-party.env'], 16384, 0o600),
                        'Credential mismatch; preserve known-good private copy for diagnosis')
                replace_session(original)
                ctl('reset-failed', SERVICE, 'pink-party-backup.service')
                ctl('restart', SERVICE)
                until(health, 'normal cleanup health')
                check_session(original)
            normal_data = True
        except Exception:
            import traceback
            log.write(traceback.format_exc().encode())
        # Resume each independent schedule even if data/service recovery failed.
        timers_ok = True
        cleanup_start = now()
        for timer in [MONITOR, TIMER]:
            try:
                ctl('start', timer)
            except Exception:
                timers_ok = False
                import traceback
                log.write(traceback.format_exc().encode())
        try:
            if normal_data and timers_ok:
                sample = until(lambda: scheduled_up(cleanup_start), 'normal scheduled recovery')
                report['normalScheduledHealth'] = sample
            cleanup_ok = normal_data and timers_ok and health() and active(MONITOR) and active(TIMER)
        except Exception:
            import traceback
            log.write(traceback.format_exc().encode())
        report['normalConfigurationRestored'] = cleanup_ok
        report['finishedAt'] = now()
        write_private(work / 'report.json', (json.dumps(report, indent=2) + '\n').encode())
        log.close()
        LOCK.rmdir()
    require(report.get('passed') and cleanup_ok, 'Exercise incomplete; inspect private reports')
    print(json.dumps(report, indent=2))


if __name__ == '__main__':
    os.chdir(APP)
    main()

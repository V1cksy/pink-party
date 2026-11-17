#!/usr/bin/env python3
"""Authenticate scheduled guest exports before rolling publication; never start a VM."""

import argparse
import base64
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile

LINUX = Path(__file__).resolve().parents[1] / 'linux'
sys.path.insert(0, str(LINUX))
from freshness import (backup, Fault, require, now, age, instant, read_json, atomic_json,
                       read_state, check_state, run_job, CAPTURE_MAX, ATTEMPT_MAX)

def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

encrypted = load('encrypted', LINUX / 'encrypted-backup.py')
vault = load('vault', Path(__file__).with_name('vault.py'))
KEEP = 7


def configuration(path):
    backup.private_directory(path.parent)
    config = read_json(path)
    require(isinstance(config, dict) and set(config) == {'version', 'vm', 'store', 'state', 'identity'}
            and config['version'] == 1, 'config-invalid')
    for field in ['store', 'state', 'identity']:
        require(isinstance(config[field], str) and Path(config[field]).is_absolute(), 'config-invalid')
        config[field] = Path(config[field])
    directories = [config['store'], config['state'], config['identity'].parent]
    require(all(a != b and a not in b.parents and b not in a.parents
                for i, a in enumerate(directories) for b in directories[i + 1:]), 'config-invalid')
    return config


def initialize(config):
    # Never adopt an existing vault as a rolling pruning target.
    for name in ['store', 'state']:
        config[name].mkdir(mode=0o700)
    atomic_json(config['store'] / 'rolling.json', {'version': 1, 'keep': KEEP})


def check_store(store):
    backup.private_directory(store)
    require(read_json(store / 'rolling.json') == {'version': 1, 'keep': KEEP}, 'not-rolling-store')
    copies = []
    for path in store.iterdir():
        if path.name in ['rolling.json', '.lock'] or path.name.startswith('.collect-'):
            continue
        require(path.suffix == '.age' and encrypted.EXPORT_NAME.fullmatch(path.stem), 'store-invalid')
        backup.read_regular(path, encrypted.CIPHER_LIMIT, 0o600)
        copies.append(path)
    require(len(copies) <= KEEP + 1, 'store-full')
    return sorted(copies)


def authenticate(cipher, identity, work, record=None):
    try:
        with encrypted.decrypted_backup(cipher, identity, work) as snapshot:
            _, manifest = backup.validate_backup(snapshot)
            digest = backup.digest(backup.read_regular(snapshot / 'snapshot.tar', backup.ARCHIVE_LIMIT, 0o600))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise Fault('authentication-or-validation-failed') from error
    if record:
        require(manifest['capturedAt'] == record['capturedAt'] and digest == record['archiveDigest'],
                'capture-mismatch')
    return manifest, digest


def source_healthy(source, at, received=False):
    if received:
        require(abs((instant(at) - instant(source['observedAt'])).total_seconds()) <= 30, 'source-clock-skew')
    else:
        age(source['observedAt'], at, ATTEMPT_MAX)
    check_state(source['backup'], at, CAPTURE_MAX)
    return check_state(source['export'], at, ATTEMPT_MAX)


def collect(config, previous, transfer=vault.request_offer):
    store = config['store']
    with backup.locked(store):
        encrypted.clear_staging(store, '.collect-*')
        encrypted.clear_staging(config['state'], '.verify-*')
        copies = check_store(store)
        with tempfile.TemporaryDirectory(prefix='.collect-', dir=store) as temporary:
            work = Path(temporary)
            try:
                offer = json.loads(transfer(config['vm'], work / 'offer.json'))
            except (OSError, ValueError, subprocess.SubprocessError) as error:
                raise Fault('source-unavailable-or-transfer-failed') from error
            at = now()
            record = source_healthy(offer['source'], at, received=True)
            require(encrypted.EXPORT_NAME.fullmatch(record['export']), 'state-invalid')
            age(record['exportedAt'], at, CAPTURE_MAX)
            if previous:
                require(instant(record['capturedAt']) >= instant(previous['capturedAt']), 'capture-rollback')
            target = store / (record['export'] + '.age')
            require(len(copies) < KEEP + 1 or target in copies, 'store-full')
            try:
                cipher = base64.b64decode(offer['ciphertext'], validate=True)
            except (ValueError, TypeError):
                raise Fault('ciphertext-invalid') from None
            require(0 < len(cipher) <= encrypted.CIPHER_LIMIT and backup.digest(cipher) == record['cipherDigest'],
                    'ciphertext-mismatch')
            stage = work / 'snapshot.age'
            backup.write_private(stage, cipher)
            # Decryption can leave key/plaintext after SIGKILL. Keep that outside the encrypted store.
            with tempfile.TemporaryDirectory(prefix='.verify-', dir=config['state']) as verification:
                authenticate(stage, config['identity'], Path(verification), record)
            collected_at = at
            if target in copies:
                require(backup.read_regular(target, encrypted.CIPHER_LIMIT, 0o600) == cipher, 'local-copy-changed')
                if previous and previous['export'] == record['export']:
                    collected_at = previous['collectedAt']
            else:
                backup.sync_directory(work)
                os.rename(stage, target)
                backup.sync_directory(store)
                copies.append(target)
            # Only one retirement is possible. A failure leaves the previous success record unchanged.
            if len(copies) > KEEP:
                protected = store / (previous['export'] + '.age') if previous else target
                oldest = next(p for p in sorted(copies) if p not in [target, protected])
                oldest.unlink()
                backup.sync_directory(store)
            source = {k: ({**v, 'history': []} if isinstance(v, dict) else v)
                      for k, v in offer['source'].items()}
            return {**record, 'collectedAt': collected_at, 'validatedAt': now(), 'source': source}, 'validated'


def inspect(config):
    at = now()
    healthy = False
    try:
        state = read_state(config['state'])
        if state and state['outcome'] == 'error':
            age(state['attemptedAt'], at, ATTEMPT_MAX)
            raise Fault('job-error:' + state['reason'])
        record = check_state(state, at, ATTEMPT_MAX)
        source_healthy(record['source'], at)
        age(record['validatedAt'], at, ATTEMPT_MAX)
        with backup.locked(config['store']):
            check_store(config['store'])
            target = config['store'] / (record['export'] + '.age')
            data = backup.read_regular(target, encrypted.CIPHER_LIMIT, 0o600)
            require(backup.digest(data) == record['cipherDigest'], 'local-copy-changed')
        reason = 'fresh-authenticated-copy'
        healthy = True
    except (OSError, ValueError, KeyError, TypeError) as error:
        reason = str(error) if isinstance(error, Fault) else 'state-or-copy-invalid'
        state = None
        try:
            state = read_state(config['state'])
        except (OSError, ValueError):
            pass
    success = state['success'] if state else None
    return {'observedAt': at, 'healthy': healthy, 'reason': reason,
            'attemptedAt': state['attemptedAt'] if state else None,
            'finishedAt': state['finishedAt'] if state else None,
            'lastSuccessfulExportAt': success['exportedAt'] if success else None,
            'lastCollectedAt': success['collectedAt'] if success else None,
            'lastAuthenticatedAt': success['validatedAt'] if success else None,
            'capturedAt': success['capturedAt'] if success else None}


def bounded_run(config_path, script=Path(__file__), timeout=90, arguments=None):
    def interrupted(signum, frame):
        raise InterruptedError('collection interrupted')
    previous_handler = signal.signal(signal.SIGTERM, interrupted)
    child = subprocess.Popen([sys.executable, '-B', str(script.resolve()),
                              *(arguments or ['worker', str(config_path)])],
                             start_new_session=True)
    try:
        return child.wait(timeout=timeout)
    except (subprocess.TimeoutExpired, KeyboardInterrupt, InterruptedError):
        os.killpg(child.pid, signal.SIGTERM)
        try:
            child.wait(timeout=2)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait(timeout=2)
        return 1
    finally:
        # limactl may leave SSH descendants when its own timeout fires. Reap the entire worker group.
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        signal.signal(signal.SIGTERM, previous_handler)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['init', 'run', 'worker', 'inspect'])
    parser.add_argument('config', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    if args.command == 'run':
        return bounded_run(args.config)
    config = configuration(args.config)
    if args.command == 'init':
        initialize(config)
    elif args.command == 'inspect':
        result = inspect(config)
        print(json.dumps(result))
        return 0 if result['healthy'] else 1
    else:
        run_job(config['state'], lambda previous: collect(config, previous))
        print('Collection authenticated and validated.')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError) as error:
        print('Collection failed: ' + (str(error) if isinstance(error, Fault) else 'private-input-or-state-error'), file=sys.stderr)
        sys.exit(1)

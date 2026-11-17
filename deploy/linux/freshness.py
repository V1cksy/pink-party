"""Private bounded job records and conservative freshness checks."""

import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import time
import subprocess
import tarfile

spec = importlib.util.spec_from_file_location('backup', Path(__file__).with_name('backup.py'))
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)
CAPTURE_MAX = 1200
ATTEMPT_MAX = 180
HISTORY_MAX = 48


class Fault(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise Fault(reason)


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def instant(value):
    require(isinstance(value, str), 'state-invalid')
    try:
        result = dt.datetime.fromisoformat(value)
        require(result.tzinfo is not None, 'state-invalid')
        return result
    except (ValueError, OverflowError):
        raise Fault('state-invalid') from None


def age(value, at, maximum):
    seconds = (instant(at) - instant(value)).total_seconds()
    require(seconds >= 0, 'clock-skew')
    require(seconds <= maximum, 'stale')
    return seconds


def atomic_json(path, value):
    backup.private_directory(path.parent)
    data = (json.dumps(value, separators=(',', ':')) + '\n').encode()
    require(len(data) <= 32768, 'state-invalid')
    fd, temporary = tempfile.mkstemp(prefix='.state-', dir=path.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            os.fchmod(stream.fileno(), 0o600)
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        backup.sync_directory(path.parent)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def read_json(path):
    return json.loads(backup.read_regular(path, 32768, 0o600))


def read_state(directory):
    backup.private_directory(directory)
    path = directory / 'status.json'
    if not path.exists() and not path.is_symlink():
        return None
    try:
        state = read_json(path)
        require(isinstance(state, dict) and set(state) == {
            'version', 'attemptedAt', 'finishedAt', 'outcome', 'reason', 'success', 'history'}, 'state-invalid')
        require(state['version'] == 1 and state['outcome'] in ['running', 'success', 'error']
                and isinstance(state['reason'], str) and len(state['reason']) <= 64
                and isinstance(state['history'], list) and len(state['history']) <= HISTORY_MAX,
                'state-invalid')
        instant(state['attemptedAt'])
        if state['outcome'] != 'running':
            require(instant(state['finishedAt']) >= instant(state['attemptedAt']), 'clock-skew')
        require(state['success'] is None or isinstance(state['success'], dict), 'state-invalid')
        return state
    except (OSError, ValueError, TypeError, KeyError):
        raise Fault('state-invalid') from None


def check_state(state, at, maximum):
    require(state is not None, 'missing-state')
    age(state['attemptedAt'], at, maximum)
    require(state['outcome'] == 'success', 'job-' + state['outcome'])
    age(state['finishedAt'], at, maximum)
    require(state['success'] is not None, 'missing-success')
    age(state['success']['capturedAt'], at, CAPTURE_MAX)
    return state['success']


def run_job(directory, operation):
    # State lock is separate from payload locks; an interrupted attempt remains visibly running.
    with backup.locked(directory):
        for path in directory.glob('.state-*'):
            backup.read_regular(path, 32768, 0o600)
            path.unlink()
        state = read_state(directory)
        started = now()
        if state:
            age(state['attemptedAt'], started, float('inf'))
            if state['finishedAt']:
                age(state['finishedAt'], started, float('inf'))
        previous = state['success'] if state else None
        history = state['history'] if state else []
        state = dict(version=1, attemptedAt=started, finishedAt=None, outcome='running',
                     reason='in-progress', success=previous, history=history)
        atomic_json(directory / 'status.json', state)
        tick = time.monotonic()
        try:
            success, reason = operation(previous)
            finished = now()
            age(started, finished, float('inf'))
            state.update(outcome='success', reason=reason, success=success, finishedAt=finished)
        except (OSError, ValueError, KeyError, TypeError, RuntimeError, subprocess.SubprocessError, tarfile.TarError) as error:
            reason = str(error) if isinstance(error, Fault) else 'operation-failed'
            state.update(outcome='error', reason=reason, finishedAt=now())
            atomic_json(directory / 'error.json', {'at': state['finishedAt'], 'type': type(error).__name__,
                                                  'detail': str(error)[:2048]})
            raise Fault(reason) from None
        finally:
            if state['outcome'] != 'running':
                state['history'] = (history + [dict(at=started, outcome=state['outcome'],
                    reason=state['reason'], durationMs=round((time.monotonic() - tick) * 1000))])[-HISTORY_MAX:]
                atomic_json(directory / 'status.json', state)
        return state

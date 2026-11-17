#!/usr/bin/env python3
"""Install and control the current user's opt-in encrypted collection LaunchAgent."""

import argparse
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile

from collector import configuration, check_store, backup, require

LABEL = 'org.pinkparty.encrypted-collection'
ROOT = Path.home() / 'Library/Application Support/PinkPartyAutomation'
PLIST = Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
DOMAIN = 'gui/' + str(os.getuid())
TARGET = DOMAIN + '/' + LABEL


def ctl(*args):
    return subprocess.run(['launchctl', *args], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, timeout=10).returncode


def install(config_file, interval=60):
    config = configuration(config_file)
    check_store(config['store'])
    require(ctl('print', TARGET) != 0 and not PLIST.exists(), 'agent-already-installed')
    ROOT.mkdir(mode=0o700, exist_ok=True)
    backup.private_directory(ROOT)
    source = Path(__file__).resolve().parents[2]
    runtime = ROOT / 'runtime'
    require(not runtime.exists(), 'runtime-already-installed')
    # A user agent cannot rely on Desktop access. Install only public helpers and validators.
    with tempfile.TemporaryDirectory(prefix='.install-', dir=ROOT) as temporary:
        stage = Path(temporary) / 'runtime'
        for directory in ['deploy/linux', 'deploy/recovery', 'server']:
            (stage / directory).mkdir(parents=True, mode=0o700)
        for relative in ['deploy/linux/backup.py', 'deploy/linux/encrypted-backup.py',
                         'deploy/linux/freshness.py', 'deploy/recovery/collector.py',
                         'deploy/recovery/vault.py', 'server/session.ts', 'server/config.ts']:
            backup.write_private(stage / relative, (source / relative).read_bytes())
        os.rename(stage, runtime)
    value = {'Label': LABEL, 'ProgramArguments': [sys.executable, '-B',
        str(runtime / 'deploy/recovery/collector.py'), 'run', str(config_file.resolve())],
        'StartInterval': interval, 'RunAtLoad': False, 'ProcessType': 'Background', 'Umask': 63,
        'EnvironmentVariables': {'PATH': '/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin'},
        'StandardOutPath': '/dev/null', 'StandardErrorPath': '/dev/null', 'ExitTimeOut': 5}
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    backup.write_private(PLIST, plistlib.dumps(value))
    require(ctl('disable', TARGET) == 0, 'launchctl-failed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['install', 'enable', 'inspect', 'disable', 'remove'])
    parser.add_argument('--config', type=Path)
    parser.add_argument('--interval', type=int, choices=[15, 60], default=60,
                        help='60 seconds normally; 15 only for a bounded failure exercise')
    args = parser.parse_args()
    require(sys.platform == 'darwin' and os.geteuid() != 0, 'run-as-mac-user')
    os.umask(0o077)
    if args.command == 'install':
        require(args.config is not None, 'config-required')
        install(args.config, args.interval)
    elif args.command == 'enable':
        backup.read_regular(PLIST, 16384, 0o600)
        require(ctl('enable', TARGET) == 0 and ctl('bootstrap', DOMAIN, str(PLIST)) == 0, 'launchctl-failed')
    elif args.command == 'inspect':
        print('LaunchAgent loaded: ' + str(ctl('print', TARGET) == 0) + '; installed: ' + str(PLIST.exists()))
    else:
        if ctl('print', TARGET) == 0:
            require(ctl('bootout', TARGET) == 0, 'launchctl-failed')
        require(ctl('disable', TARGET) == 0, 'launchctl-failed')
        if args.command == 'remove':
            if PLIST.exists():
                backup.read_regular(PLIST, 16384, 0o600)
                PLIST.unlink()
            if (ROOT / 'runtime').exists():
                backup.private_directory(ROOT)
                shutil.rmtree(ROOT / 'runtime')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.SubprocessError):
        print('LaunchAgent operation failed; inspect private configuration and user service state.', file=sys.stderr)
        sys.exit(1)

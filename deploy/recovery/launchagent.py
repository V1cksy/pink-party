#!/usr/bin/env python3
"""Control the current user's opt-in encrypted backup LaunchAgents."""

import argparse
import os
from pathlib import Path
import plistlib
import shutil
import subprocess
import sys
import tempfile

from collector import configuration, check_store, backup, require
from offsite import configuration as offsite_configuration

DOMAIN = 'gui/' + str(os.getuid())


class Agent:
    def __init__(self, offsite):
        self.offsite = offsite
        self.label = 'org.pinkparty.' + ('offsite-backup' if offsite else 'encrypted-collection')
        self.root = Path.home() / 'Library/Application Support' / (
            'PinkPartyOffsite' if offsite else 'PinkPartyAutomation')
        self.plist = Path.home() / 'Library/LaunchAgents' / (self.label + '.plist')
        self.target = DOMAIN + '/' + self.label


def ctl(*args):
    return subprocess.run(['launchctl', *args], stdout=subprocess.DEVNULL,
                          stderr=subprocess.DEVNULL, timeout=10).returncode


def install(agent, config_file, interval):
    if agent.offsite:
        offsite_configuration(config_file, writer=True)
    else:
        config = configuration(config_file)
        check_store(config['store'])
    require(ctl('print', agent.target) != 0 and not agent.plist.exists(), 'agent-already-installed')
    agent.root.mkdir(mode=0o700, exist_ok=True)
    backup.private_directory(agent.root)
    source = Path(__file__).resolve().parents[2]
    runtime = agent.root / 'runtime'
    require(not runtime.exists(), 'runtime-already-installed')
    # A user agent cannot rely on Desktop access. Install only public helpers and validators.
    with tempfile.TemporaryDirectory(prefix='.install-', dir=agent.root) as temporary:
        stage = Path(temporary) / 'runtime'
        for directory in ['deploy/linux', 'deploy/recovery', 'server']:
            (stage / directory).mkdir(parents=True, mode=0o700)
        files = ['deploy/linux/backup.py', 'deploy/linux/encrypted-backup.py',
                         'deploy/linux/freshness.py', 'deploy/recovery/collector.py',
                         'deploy/recovery/vault.py', 'server/session.ts', 'server/config.ts']
        if agent.offsite:
            files.append('deploy/recovery/offsite.py')
        for relative in files:
            backup.write_private(stage / relative, (source / relative).read_bytes())
        os.rename(stage, runtime)
    worker = 'offsite.py' if agent.offsite else 'collector.py'
    value = {'Label': agent.label, 'ProgramArguments': [sys.executable, '-B',
        str(runtime / 'deploy/recovery' / worker), 'run', str(config_file.resolve())],
        'StartInterval': interval, 'RunAtLoad': False, 'ProcessType': 'Background', 'Umask': 63,
        'EnvironmentVariables': {'PATH': '/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin'},
        'StandardOutPath': '/dev/null', 'StandardErrorPath': '/dev/null', 'ExitTimeOut': 5}
    agent.plist.parent.mkdir(parents=True, exist_ok=True)
    backup.write_private(agent.plist, plistlib.dumps(value))
    require(ctl('disable', agent.target) == 0, 'launchctl-failed')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['install', 'enable', 'inspect', 'disable', 'remove'])
    parser.add_argument('--offsite', action='store_true')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--interval', type=int, choices=[15, 60, 75],
                        help='Default: collection 60 seconds, offsite 75; 15 only for failure exercises')
    args = parser.parse_args()
    require(sys.platform == 'darwin' and os.geteuid() != 0, 'run-as-mac-user')
    os.umask(0o077)
    agent = Agent(args.offsite)
    if args.command == 'install':
        require(args.config is not None, 'config-required')
        install(agent, args.config, args.interval or (75 if args.offsite else 60))
    elif args.command == 'enable':
        backup.read_regular(agent.plist, 16384, 0o600)
        require(ctl('enable', agent.target) == 0 and ctl('bootstrap', DOMAIN, str(agent.plist)) == 0, 'launchctl-failed')
    elif args.command == 'inspect':
        print('LaunchAgent loaded: ' + str(ctl('print', agent.target) == 0) + '; installed: ' + str(agent.plist.exists()))
    else:
        if ctl('print', agent.target) == 0:
            require(ctl('bootout', agent.target) == 0, 'launchctl-failed')
        require(ctl('disable', agent.target) == 0, 'launchctl-failed')
        if args.command == 'remove':
            if agent.plist.exists():
                backup.read_regular(agent.plist, 16384, 0o600)
                agent.plist.unlink()
            if (agent.root / 'runtime').exists():
                backup.private_directory(agent.root)
                shutil.rmtree(agent.root / 'runtime')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, subprocess.SubprocessError):
        print('LaunchAgent operation failed; inspect private configuration and user service state.', file=sys.stderr)
        sys.exit(1)

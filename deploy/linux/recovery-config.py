#!/usr/bin/env python3
"""Validate local-only recovered inputs before fresh installation."""

import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys

from backup import (LIMIT, MODES, private_directory, read_regular, require,
                    sync_directory, validate_payloads, write_private)

FRESH_PATHS = ['opt/pink-party/app', 'opt/pink-party/node', 'opt/pink-party/bin',
               'opt/pink-party/previous', 'etc/pink-party', 'var/lib/pink-party',
               'var/lib/pink-party-monitor', 'var/lib/pink-party-backups']
UNITS = ['pink-party.service', 'pink-party-monitor.service', 'pink-party-monitor.timer',
         'pink-party-backup.service', 'pink-party-backup.timer', 'pink-party-https.service']


def require_fresh(root=Path('/')):
    for relative in FRESH_PATHS + ['etc/systemd/system/' + name for name in UNITS]:
        target = root / relative
        require(not target.exists() and not target.is_symlink(),
                'Recovery requires a fresh guest with no application installation or state')
        require(all(not parent.is_symlink() for parent in target.parents),
                'Recovery destination ancestors must not be symlinks')


def recovered_payloads(directory):
    private_directory(directory)
    require({p.name for p in directory.iterdir()} == {'data', 'private'},
            'Unexpected recovery files')
    for folder, name in [('data', 'session.json'), ('private', 'pink-party.env')]:
        private_directory(directory / folder)
        require({p.name for p in (directory / folder).iterdir()} == {name},
                'Unexpected recovery files')
    payloads = {name: read_regular(directory / name, LIMIT, mode)
                for name, mode in MODES.items()}
    validate_payloads(payloads)
    fields = dict(line.split('=', 1) for line in payloads['private/pink-party.env'].decode('ascii').splitlines())
    require(fields['PINK_PARTY_MODE'] == 'local', 'Recovery installer accepts Linux local mode only')
    return payloads


def stage_recovery(source, destination):
    private_directory(destination.parent)
    require(not destination.exists() and not destination.is_symlink(),
            'Recovery staging destination already exists')
    payloads = recovered_payloads(source)
    destination.mkdir(mode=0o700)
    try:
        for folder in ['data', 'private']:
            (destination / folder).mkdir(mode=0o700)
        for name, data in payloads.items():
            write_private(destination / name, data, MODES[name])
        require(recovered_payloads(destination) == payloads, 'Recovery staging mismatch')
        require(recovered_payloads(source) == payloads, 'Recovery inputs changed during staging')
        sync_directory(destination)
    except BaseException:
        shutil.rmtree(destination)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('check-fresh')
    stage = commands.add_parser('stage')
    stage.add_argument('source', type=Path)
    stage.add_argument('destination', type=Path)
    args = parser.parse_args()
    require(sys.platform == 'linux' and os.geteuid() == 0, 'Run as root inside Linux')
    os.umask(0o077)
    if args.command == 'check-fresh':
        require_fresh()
    else:
        stage_recovery(args.source, args.destination)


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError):
        print('Recovery inputs rejected; inspect fresh-guest state, local mode, schema, ownership and modes.', file=sys.stderr)
        sys.exit(1)

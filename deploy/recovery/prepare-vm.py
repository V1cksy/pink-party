#!/usr/bin/env python3
"""Create a task-scoped disposable recovery VM and transfer reviewed public source and recovery inputs."""

import argparse
import json
import os
from pathlib import Path
import subprocess

RECOVERY_VMS = {'8': 'pink-party-recovery-b8', '11': 'pink-party-recovery-b11'}


def run(*args, timeout=300):
    subprocess.run(list(args), check=True, timeout=timeout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('encrypted', type=Path)
    parser.add_argument('identity', type=Path)
    parser.add_argument('--batch', choices=RECOVERY_VMS, default='8')
    args = parser.parse_args()
    vm = RECOVERY_VMS[args.batch]
    os.umask(0o077)
    os.environ['COPYFILE_DISABLE'] = '1'
    repo = Path(__file__).resolve().parents[2]
    inventory = subprocess.check_output(['limactl', 'list', '--json'], timeout=5).decode().splitlines()
    for row in map(json.loads, inventory):
        if row['name'] == vm or row['status'] != 'Stopped':
            raise RuntimeError('All guests must be stopped and the disposable guest must be absent')
    # Validation enforces size/type/modes before copying either private input.
    import importlib.util
    spec = importlib.util.spec_from_file_location('encrypted', repo / 'deploy/linux/encrypted-backup.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.read_identity(args.identity.absolute())
    module.backup.private_directory(args.encrypted.absolute().parent)
    module.backup.read_regular(args.encrypted.absolute(), module.CIPHER_LIMIT, 0o600)
    work = repo / '.local' / ('recovery-transfer' if args.batch == '8' else 'batch11/recovery-transfer')
    if args.batch == '11':
        for directory in [work.parent.parent, work.parent]:
            directory.mkdir(mode=0o700, exist_ok=True)
            module.backup.private_directory(directory)
    work.mkdir(mode=0o700, exist_ok=True)
    module.backup.private_directory(work)
    archive = work / 'public-source.tar'
    run('bash', str(repo / 'deploy/linux/archive.sh'), str(repo), str(archive))
    run('limactl', 'start', '--name=' + vm, '--tty=false', '--timeout=5m', str(repo / 'deploy/linux/lima.yaml'), timeout=330)
    stage = '/tmp/pink-party-recovery-input'
    run('limactl', 'shell', '--workdir=/tmp', vm, 'mkdir', '-m', '0700', stage, timeout=15)
    for path, name in [(archive, 'public-source.tar'), (args.encrypted, 'snapshot.age'), (args.identity, 'recovery.agekey')]:
        run('limactl', 'copy', str(path), vm + ':' + stage + '/' + name, timeout=30)
    run('limactl', 'shell', '--workdir=/tmp', vm, 'sudo', 'bash', '-c', '''
set -euo pipefail
umask 077
cd /tmp/pink-party-recovery-input
trap 'rm -f public-source.tar snapshot.age recovery.agekey; cd /tmp; rmdir pink-party-recovery-input' EXIT
install -d -m 0700 /var/lib/pink-party-restores /var/lib/pink-party-restores/key /var/lib/pink-party-restores/input /var/lib/pink-party-restores/decrypt-work /root/pink-party-source
install -m 0600 recovery.agekey /var/lib/pink-party-restores/key/recovery.agekey
install -m 0600 snapshot.age /var/lib/pink-party-restores/input/snapshot.age
tar --no-same-owner -xf public-source.tar -C /root/pink-party-source
''', timeout=40)
    print('Disposable recovery VM prepared; original guest remains stopped. No host folders or application ports forwarded.')


if __name__ == '__main__':
    main()

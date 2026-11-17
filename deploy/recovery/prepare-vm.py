#!/usr/bin/env python3
"""Create only the disposable batch-8 VM and transfer reviewed public source and recovery inputs."""

import argparse
import json
import os
from pathlib import Path
import subprocess

VM = 'pink-party-recovery-b8'


def run(*args, timeout=300):
    subprocess.run(list(args), check=True, timeout=timeout)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('encrypted', type=Path)
    parser.add_argument('identity', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    os.environ['COPYFILE_DISABLE'] = '1'
    repo = Path(__file__).resolve().parents[2]
    source = json.loads(subprocess.check_output(['limactl', 'list', 'pink-party', '--json'], timeout=5))
    if source['status'] != 'Stopped':
        raise RuntimeError('Stop the original source VM before creating recovery VM')
    inventory = subprocess.check_output(['limactl', 'list', '--json'], timeout=5).decode().splitlines()
    if any(json.loads(row)['name'] == VM for row in inventory):
        raise RuntimeError('Recovery VM already exists; inspect it before retrying')
    # Validation enforces size/type/modes before copying either private input.
    import importlib.util
    spec = importlib.util.spec_from_file_location('encrypted', repo / 'deploy/linux/encrypted-backup.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.read_identity(args.identity.absolute())
    module.backup.private_directory(args.encrypted.absolute().parent)
    module.backup.read_regular(args.encrypted.absolute(), module.CIPHER_LIMIT, 0o600)
    work = repo / '.local/recovery-transfer'
    work.mkdir(mode=0o700, exist_ok=True)
    module.backup.private_directory(work)
    archive = work / 'public-source.tar'
    run('bash', str(repo / 'deploy/linux/archive.sh'), str(repo), str(archive))
    run('limactl', 'start', '--name=' + VM, '--tty=false', '--timeout=5m', str(repo / 'deploy/linux/lima.yaml'), timeout=330)
    for path, name in [(archive, 'public-source.tar'), (args.encrypted, 'snapshot.age'), (args.identity, 'recovery.agekey')]:
        run('limactl', 'copy', str(path), VM + ':/tmp/batch8-' + name, timeout=30)
    run('limactl', 'shell', '--workdir=/tmp', VM, 'sudo', 'bash', '-c', '''
set -euo pipefail
umask 077
trap 'rm -f /tmp/batch8-public-source.tar /tmp/batch8-snapshot.age /tmp/batch8-recovery.agekey' EXIT
install -d -m 0700 /var/lib/pink-party-restores /var/lib/pink-party-restores/key /var/lib/pink-party-restores/input /var/lib/pink-party-restores/decrypt-work /root/pink-party-source
install -m 0600 /tmp/batch8-recovery.agekey /var/lib/pink-party-restores/key/recovery.agekey
install -m 0600 /tmp/batch8-snapshot.age /var/lib/pink-party-restores/input/snapshot.age
tar --no-same-owner -xf /tmp/batch8-public-source.tar -C /root/pink-party-source
''', timeout=40)
    print('Disposable recovery VM prepared; original guest remains stopped. No host folders or application ports forwarded.')


if __name__ == '__main__':
    main()

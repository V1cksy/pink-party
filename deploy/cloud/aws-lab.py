#!/usr/bin/env python3
"""Create only on a verified AWS Free plan; keep resource state private."""
import argparse
import base64
import datetime as dt
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import subprocess
import tempfile
import time
import uuid

REGION = 'eu-north-1'
ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / '.local/cloud/aws-state.json'
TEMPLATE = Path(__file__).with_name('aws-template.json')
AMI_PARAMETER = '/aws/service/canonical/ubuntu/server/24.04/stable/current/arm64/hvm/ebs-gp3/ami-id'


def require(value, reason):
    if not value:
        raise ValueError(reason)


def free_plan(plan, now):
    require(plan.get('accountPlanType') == 'FREE' and plan.get('accountPlanStatus') == 'ACTIVE',
            'An ACTIVE FREE account plan is required; PAID credits are not spending protection')
    credit = plan.get('accountPlanRemainingCredits', {})
    amount = float(credit.get('amount', 0))
    require(credit.get('unit') == 'USD' and math.isfinite(amount) and amount >= 1,
            'At least USD 1 in remaining Free-plan credits is required')
    expiry = dt.datetime.fromisoformat(str(plan.get('accountPlanExpirationDate', '')).replace('Z', '+00:00'))
    require(expiry.tzinfo is not None and expiry - now >= dt.timedelta(hours=4),
            'At least four hours of Free-plan lifetime is required')


def check_image(image):
    require(image.get('OwnerId') == '099720109477' and image.get('Architecture') == 'arm64'
            and image.get('State') == 'available' and image.get('RootDeviceType') == 'ebs'
            and image.get('RootDeviceName') == '/dev/sda1'
            and image.get('VirtualizationType') == 'hvm'
            and re.fullmatch(r'ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24\.04-arm64-server-\d{8}', image.get('Name', '')),
            'Expected an available official Canonical Ubuntu 24.04 ARM64 gp3 image')
    devices = image.get('BlockDeviceMappings', [])
    roots = [d for d in devices if d.get('DeviceName') == '/dev/sda1']
    # Canonical also publishes legacy instance-store placeholders. T4g has no instance store.
    others = [d for d in devices if d.get('DeviceName') != '/dev/sda1']
    require(len(roots) == 1 and roots[0].get('Ebs', {}).get('VolumeSize', 100) <= 12
            and all(set(d) == {'DeviceName', 'VirtualName'} and
                    (d['DeviceName'], d['VirtualName']) in [('/dev/sdb', 'ephemeral0'), ('/dev/sdc', 'ephemeral1')]
                    for d in others),
            'Unexpected image disk layout or size')


def request_parameters(cidr, key):
    network = ipaddress.ip_network(cidr, strict=True)
    require(network.version == 4 and network.prefixlen == 32 and network.network_address.is_global,
            'Use exactly one public administrator IPv4 address with /32')
    require(len(key) < 1024 and re.fullmatch(r'ssh-ed25519 [A-Za-z0-9+/=]+(?: [^\r\n]+)?', key),
            'Use a new lab-only ed25519 public SSH key')
    return [{'ParameterKey': 'AdminCidr', 'ParameterValue': str(network)},
            {'ParameterKey': 'PublicKey', 'ParameterValue': key}]


def private_write(path, value):
    path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
    require(not path.parent.is_symlink() and path.parent.stat().st_uid == os.getuid()
            and path.parent.stat().st_mode & 0o777 == 0o700, 'State directory must be owned mode 0700')
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '-', suffix='.tmp', dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(value, stream, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def load_state():
    info = STATE.lstat()
    require(STATE.is_file() and not STATE.is_symlink() and info.st_uid == os.getuid()
            and info.st_mode & 0o777 == 0o600, 'Unsafe state file')
    return json.loads(STATE.read_text())


class Aws:
    def __init__(self, profile):
        self.profile = profile

    def __call__(self, *args, region=REGION):
        result = subprocess.run(['aws', '--profile', self.profile, '--region', region,
                                 '--no-cli-pager', '--output', 'json', '--cli-connect-timeout', '10',
                                 '--cli-read-timeout', '25', *args], capture_output=True, text=True,
                                timeout=40, env={**os.environ, 'AWS_PAGER': '', 'AWS_CLI_AUTO_PROMPT': 'off'})
        if result.returncode:
            private_write(STATE.parent / 'last-error.json', {'command': list(args[:2]), 'stderr': result.stderr})
            raise RuntimeError('AWS command failed; inspect the private last-error.json. No upgrade or fallback was attempted.')
        return json.loads(result.stdout or '{}')


def preflight(aws):
    identity = aws('sts', 'get-caller-identity')
    plan = aws('freetier', 'get-account-plan-state', region='us-east-1')
    free_plan(plan, dt.datetime.now(dt.timezone.utc))
    require(plan['accountId'] == identity['Account'], 'Plan/account mismatch')
    return identity, plan


def wait_stack(aws, state, deleting=False):
    deadline = time.monotonic() + 900
    while time.monotonic() < deadline:
        stacks = aws('cloudformation', 'list-stacks')['StackSummaries']
        row = next((s for s in stacks if s['StackId'] == state['stackId']), None)
        if row and row['StackStatus'] == ('DELETE_COMPLETE' if deleting else 'CREATE_COMPLETE'):
            return
        require(not row or row['StackStatus'] not in ['CREATE_FAILED', 'ROLLBACK_COMPLETE', 'ROLLBACK_FAILED', 'DELETE_FAILED',
                                                    *([] if deleting else ['DELETE_IN_PROGRESS', 'DELETE_COMPLETE'])],
                'Stack failed; inspect private state and perform teardown')
        time.sleep(10)
    raise ValueError('Stack wait timed out; state was retained. Inspect and destroy the lab')


def recover_stack(aws, state):
    rows = aws('cloudformation', 'list-stacks')['StackSummaries']
    matches = [s for s in rows if s['StackName'] == state['stackName']]
    require(len(matches) == 1, 'Cannot identify the stack; inspect private creation evidence')
    state['stackId'] = matches[0]['StackId']
    return matches[0]


def inventory(aws, state):
    lab = 'Name=tag:PinkPartyLab,Values=' + state['labId']
    results = {}
    for operation, key in [('describe-instances', 'Reservations'), ('describe-volumes', 'Volumes'),
                           ('describe-snapshots', 'Snapshots'), ('describe-addresses', 'Addresses'),
                           ('describe-vpcs', 'Vpcs')]:
        results[key] = aws('ec2', operation, '--filters', lab)[key]
    return results


def assert_removed(value):
    require(all(i['State']['Name'] == 'terminated' for r in value['Reservations'] for i in r['Instances']),
            'Lab instance still exists')
    require(not any(value[k] for k in ['Volumes', 'Snapshots', 'Addresses', 'Vpcs']),
            'Lab disk, snapshot, address or VPC remains; cleanup is incomplete')


def console_host_key(output):
    if 'BEGIN SSH HOST KEY KEYS' not in output:
        try:
            output = base64.b64decode(output, validate=True).decode()
        except (ValueError, UnicodeError):
            raise ValueError('Host key is not yet present in the authenticated EC2 console output') from None
    match = re.search(r'-----BEGIN SSH HOST KEY KEYS-----(.*?)-----END SSH HOST KEY KEYS-----', output, re.S)
    require(match is not None, 'Host key is not yet present in the authenticated EC2 console output')
    keys = re.findall(r'^ssh-ed25519 ([A-Za-z0-9+/=]+)(?: [^\r\n]*)?$', match.group(1), re.M)
    require(len(keys) == 1, 'Expected exactly one ed25519 host key from EC2 console output')
    return 'ssh-ed25519 ' + keys[0]


def console_host_fingerprint(output):
    match = re.search(r'Your identification has been saved in /etc/ssh/ssh_host_ed25519_key\s*(.*?)(?:randomart|\+--\[ED25519)', output, re.S)
    require(match is not None, 'Host fingerprint not yet present in EC2 console output')
    fingerprints = re.findall(r'SHA256:[A-Za-z0-9+/=]+', match.group(1))
    require(len(fingerprints) == 1, 'Expected one ed25519 generation fingerprint from EC2 console output')
    return fingerprints[0]


def ssh_config(aws, state):
    hosts = [i for r in inventory(aws, state)['Reservations'] for i in r['Instances'] if i['State']['Name'] == 'running']
    require(len(hosts) == 1, 'Expected one running lab host')
    host = hosts[0]
    address = str(ipaddress.ip_address(host['PublicIpAddress']))
    output = aws('ec2', 'get-console-output', '--instance-id', host['InstanceId'], '--latest')
    private_write(STATE.parent / 'ssh-console.json', output)
    try:
        key = console_host_key(output['Output'])
    except ValueError:
        # Ubuntu can log generation fingerprints before cloud-init prints public keys.
        expected = console_host_fingerprint(output['Output'])
        scan = subprocess.run(['ssh-keyscan', '-T', '5', '-t', 'ed25519', address],
                              capture_output=True, text=True, timeout=15, check=True).stdout
        lines = [line for line in scan.splitlines() if not line.startswith('#')]
        require(len(lines) == 1 and lines[0].split()[:2] == [address, 'ssh-ed25519'], 'Unexpected host key scan')
        check_path = STATE.parent / 'scanned-host-key'
        check_path.write_text(lines[0] + '\n')
        check_path.chmod(0o600)
        fingerprint = subprocess.run(['ssh-keygen', '-lf', str(check_path)],
                                     capture_output=True, text=True, timeout=5, check=True).stdout.split()[1]
        require(fingerprint == expected, 'Scanned host key differs from authenticated EC2 console fingerprint')
        key = ' '.join(lines[0].split()[1:3])
    identity = STATE.parent / 'id_ed25519'
    require(identity.is_file() and identity.stat().st_mode & 0o777 == 0o600, 'Expected separate mode 0600 lab SSH key')
    known = STATE.parent / 'known_hosts'
    config = STATE.parent / 'ssh.conf'
    for path, data in [(known, address + ' ' + key + '\n'), (config,
                        'Host pink-party-cloud\n  HostName ' + address + '\n  User ubuntu\n  IdentityFile ' + str(identity) +
                        '\n  IdentitiesOnly yes\n  ForwardAgent no\n  StrictHostKeyChecking yes\n  UserKnownHostsFile ' + str(known) +
                        '\n  ConnectTimeout 10\n  ServerAliveInterval 15\n  ServerAliveCountMax 2\n')]:
        require(not path.is_symlink(), 'Symlinked SSH configuration rejected')
        path.write_text(data)
        path.chmod(0o600)
    print('Prepared private SSH configuration using the host key from authenticated EC2 console output.')


def private_ready(ssh):
    checks = ['sudo /opt/pink-party/node/bin/node /opt/pink-party/app/deploy/linux/service-health.ts']
    checks += ['systemctl is-active --quiet ' + unit for unit in [
        'pink-party-https.service', 'pink-party-monitor.timer', 'pink-party-backup.timer']]
    # systemctl is-active with multiple names succeeds when any one is active.
    return all(ssh(command).returncode == 0 for command in checks)


def reboot_check(aws, state):
    preflight(aws)
    hosts = [i for r in inventory(aws, state)['Reservations'] for i in r['Instances'] if i['State']['Name'] == 'running']
    require(len(hosts) == 1, 'Expected one running lab host')
    def ssh(command):
        return subprocess.run(['ssh', '-F', str(STATE.parent / 'ssh.conf'), 'pink-party-cloud', command],
                              capture_output=True, text=True, timeout=15)
    require(private_ready(ssh), 'Private service and both timers must start healthy')
    before = ssh('cat /proc/sys/kernel/random/boot_id; sudo sha256sum /etc/pink-party/pink-party.env')
    require(before.returncode == 0, 'Cannot inspect reboot baseline')
    report = {'requestedAt': dt.datetime.now(dt.timezone.utc).isoformat(), 'before': before.stdout}
    private_write(STATE.parent / 'reboot-validation.json', report)
    started = time.monotonic()
    aws('ec2', 'reboot-instances', '--instance-ids', hosts[0]['InstanceId'])
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        try:
            after = ssh('cat /proc/sys/kernel/random/boot_id; sudo sha256sum /etc/pink-party/pink-party.env')
            changed = after.returncode == 0 and after.stdout.splitlines()[0] != before.stdout.splitlines()[0]
            if changed and private_ready(ssh):
                require(after.stdout.splitlines()[1:] == before.stdout.splitlines()[1:], 'Credentials changed during reboot')
                report.update({'after': after.stdout, 'differentBoot': True, 'automaticStartup': True,
                               'credentialsPreserved': True, 'readyAfterMs': round((time.monotonic() - started) * 1000),
                               'verifiedAt': dt.datetime.now(dt.timezone.utc).isoformat()})
                private_write(STATE.parent / 'reboot-validation.json', report)
                print('Different guest boot and automatic private application/HTTPS/timer startup verified with unchanged credentials.')
                return
        except subprocess.TimeoutExpired:
            pass
        time.sleep(2)
    raise ValueError('Reboot readiness timed out. Inspect services and restore normal health before teardown')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['preflight', 'create', 'status', 'ssh-config', 'reboot-check', 'destroy'])
    parser.add_argument('--profile', default='pink-party-lab')
    parser.add_argument('--admin-cidr')
    parser.add_argument('--public-key-file', type=Path)
    args = parser.parse_args()
    os.umask(0o077)
    aws = Aws(args.profile)
    if args.command == 'preflight':
        preflight(aws)
        print('Verified active AWS Free plan with credit and lifetime headroom. No resources created.')
    elif args.command == 'create':
        if STATE.exists():
            old = load_state()
            require(old.get('removedAt') and old['profile'] == args.profile,
                    'Existing state preserved. Inspect or destroy that lab before creating another')
            require(aws('sts', 'get-caller-identity')['Account'] == old['account'], 'Wrong AWS account')
            assert_removed(inventory(aws, old))
            os.replace(STATE, STATE.with_name('completed-' + old['labId'] + '.json'))
        require(args.admin_cidr and args.public_key_file, 'Pass --admin-cidr and --public-key-file')
        params = request_parameters(args.admin_cidr, args.public_key_file.read_text().strip())
        identity, plan = preflight(aws)
        image_id = aws('ssm', 'get-parameter', '--name', AMI_PARAMETER)['Parameter']['Value']
        images = aws('ec2', 'describe-images', '--image-ids', image_id)['Images']
        require(len(images) == 1, 'Image lookup failed')
        check_image(images[0])
        aws('cloudformation', 'validate-template', '--template-body', 'file://' + str(TEMPLATE))
        # Recheck immediately before creation. Never upgrade the plan or enable paid-only services.
        preflight(aws)
        state = {'profile': args.profile, 'account': identity['Account'], 'labId': uuid.uuid4().hex,
                 'createdAt': dt.datetime.now(dt.timezone.utc).isoformat(), 'planBefore': plan,
                 'image': images[0], 'region': REGION}
        state['stackName'] = 'pink-party-lab-' + state['labId'][:12]
        private_write(STATE, state)
        params += [{'ParameterKey': 'ImageId', 'ParameterValue': image_id},
                   {'ParameterKey': 'LabId', 'ParameterValue': state['labId']}]
        created = aws('cloudformation', 'create-stack', '--stack-name', state['stackName'],
                      '--template-body', 'file://' + str(TEMPLATE), '--parameters', json.dumps(params),
                      '--tags', json.dumps([{'Key': 'PinkPartyLab', 'Value': state['labId']}]),
                      '--client-request-token', state['labId'], '--on-failure', 'DELETE', '--timeout-in-minutes', '15')
        state['stackId'] = created['StackId']
        private_write(STATE, state)
        wait_stack(aws, state)
        state['stack'] = aws('cloudformation', 'describe-stacks', '--stack-name', state['stackId'])['Stacks'][0]
        state['inventoryBefore'] = inventory(aws, state)
        private_write(STATE, state)
        print('Created the private-access lab. Inspect private state for SSH details. Destroy within three hours; stop is not cleanup.')
    else:
        state = load_state()
        require(state['profile'] == args.profile and state['region'] == REGION, 'State/profile mismatch')
        require(aws('sts', 'get-caller-identity')['Account'] == state['account'], 'Wrong AWS account; preserved state')
        # Recover an ambiguous create response without creating a second stack.
        if 'stackId' not in state:
            recover_stack(aws, state)
            private_write(STATE, state)
        if args.command == 'ssh-config':
            ssh_config(aws, state)
        elif args.command == 'reboot-check':
            reboot_check(aws, state)
        elif args.command == 'status':
            state['lastInventory'] = inventory(aws, state)
            private_write(STATE, state)
            print('Saved private inventory. Resource existence and usage must be checked before ending the lab.')
        else:
            row = recover_stack(aws, state)
            if row['StackStatus'] != 'DELETE_COMPLETE':
                stack = aws('cloudformation', 'describe-stacks', '--stack-name', state['stackId'])['Stacks'][0]
                require({'Key': 'PinkPartyLab', 'Value': state['labId']} in stack['Tags'], 'Stack ownership mismatch')
            try:
                state['inventoryBeforeDelete'] = inventory(aws, state)
            except (OSError, RuntimeError, KeyError, subprocess.SubprocessError):
                state['inventoryBeforeDeleteFailed'] = True
            private_write(STATE, state)
            if row['StackStatus'] != 'DELETE_COMPLETE':
                aws('cloudformation', 'delete-stack', '--stack-name', state['stackId'])
            wait_stack(aws, state, deleting=True)
            state['inventoryAfterDelete'] = inventory(aws, state)
            private_write(STATE, state)
            assert_removed(state['inventoryAfterDelete'])
            state['removedAt'] = dt.datetime.now(dt.timezone.utc).isoformat()
            private_write(STATE, state)
            print('Stack deleted; tagged instance terminated and tagged disk/address/snapshot/VPC inventory empty. Review Billing for delayed usage.')


if __name__ == '__main__':
    try:
        main()
    except (OSError, ValueError, RuntimeError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print(str(error) if type(error) in (ValueError, RuntimeError) else type(error).__name__)
        raise SystemExit(1)

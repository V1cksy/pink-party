import datetime as dt
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('cloud', Path(__file__).resolve().parents[1] / 'deploy/cloud/aws-lab.py')
cloud = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cloud)


class CloudTest(unittest.TestCase):
    def test_free_plan_rejects_paid_expired_low_credit_and_bad_units(self):
        now = dt.datetime(2026, 11, 16, tzinfo=dt.timezone.utc)
        plan = {'accountPlanType': 'FREE', 'accountPlanStatus': 'ACTIVE',
                'accountPlanRemainingCredits': {'amount': 100, 'unit': 'USD'},
                'accountPlanExpirationDate': (now + dt.timedelta(days=90)).isoformat()}
        cloud.free_plan(plan, now)
        for change in [{'accountPlanType': 'PAID'}, {'accountPlanStatus': 'EXPIRED'},
                       {'accountPlanRemainingCredits': {'amount': 0.99, 'unit': 'USD'}},
                       {'accountPlanRemainingCredits': {'amount': float('nan'), 'unit': 'USD'}},
                       {'accountPlanRemainingCredits': {'amount': 100, 'unit': 'EUR'}},
                       {'accountPlanExpirationDate': (now + dt.timedelta(hours=3)).isoformat()}]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                cloud.free_plan({**plan, **change}, now)

    def test_unsupported_image_and_wide_admin_network_fail_before_creation(self):
        for cidr in ['0.0.0.0/0', '8.8.8.0/24', '127.0.0.1/32', '::/0']:
            with self.assertRaises(ValueError):
                cloud.request_parameters(cidr, 'ssh-ed25519 AAAA fixture')
        cloud.request_parameters('8.8.8.8/32', 'ssh-ed25519 AAAA fixture')
        image = {'OwnerId': '099720109477', 'Architecture': 'arm64', 'State': 'available',
                 'RootDeviceType': 'ebs', 'RootDeviceName': '/dev/sda1', 'VirtualizationType': 'hvm',
                 'Name': 'ubuntu/images/hvm-ssd-gp3/ubuntu-noble-24.04-arm64-server-20261017',
                 'BlockDeviceMappings': [{'DeviceName': '/dev/sda1', 'Ebs': {'VolumeSize': 8}}]}
        cloud.check_image(image)
        cloud.check_image({**image, 'BlockDeviceMappings': image['BlockDeviceMappings'] + [
            {'DeviceName': '/dev/sdb', 'VirtualName': 'ephemeral0'},
            {'DeviceName': '/dev/sdc', 'VirtualName': 'ephemeral1'}]})
        for change in [{'OwnerId': 'other'}, {'Architecture': 'x86_64'}, {'State': 'pending'},
                       {'Name': 'ubuntu-pro-paid'}, {'BlockDeviceMappings': []},
                       {'BlockDeviceMappings': image['BlockDeviceMappings'] + [{'DeviceName': '/dev/sdf', 'Ebs': {'VolumeSize': 100}}]}]:
            with self.assertRaises(ValueError):
                cloud.check_image({**image, **change})

    def test_create_never_reaches_mutation_when_plan_is_paid(self):
        calls = []
        def fake(*args, **kwargs):
            calls.append(args[:2])
            if args[:2] == ('sts', 'get-caller-identity'):
                return {'Arn': 'arn:aws:iam::000000000000:user/synthetic', 'Account': '000000000000'}
            if args[:2] == ('freetier', 'get-account-plan-state'):
                return {'accountPlanType': 'PAID'}
            self.fail('Unexpected AWS call')
        with tempfile.TemporaryDirectory() as directory:
            key = Path(directory) / 'key.pub'
            key.write_text('ssh-ed25519 AAAA synthetic')
            with patch.object(cloud, 'STATE', Path(directory) / 'state.json'), patch.object(cloud, 'Aws', return_value=fake), patch('sys.argv', ['aws-lab.py', 'create', '--admin-cidr', '8.8.8.8/32', '--public-key-file', str(key)]):
                with self.assertRaisesRegex(ValueError, 'ACTIVE FREE'):
                    cloud.main()
            self.assertEqual(calls, [('sts', 'get-caller-identity'), ('freetier', 'get-account-plan-state')])

    def test_teardown_requires_terminated_instance_and_no_retained_storage(self):
        empty = {'Reservations': [], 'Volumes': [], 'Snapshots': [], 'Addresses': [], 'Vpcs': []}
        cloud.assert_removed(empty)
        for key in ['Volumes', 'Snapshots', 'Addresses', 'Vpcs']:
            with self.assertRaises(ValueError):
                cloud.assert_removed({**empty, key: [{}]})
        for state in ['running', 'stopped', 'shutting-down']:
            with self.assertRaises(ValueError):
                cloud.assert_removed({**empty, 'Reservations': [{'Instances': [{'State': {'Name': state}}]}]})

    def test_template_network_and_cost_boundaries(self):
        template = json.loads(cloud.TEMPLATE.read_text())
        resources = template['Resources']
        host = resources['Host']['Properties']
        self.assertEqual(host['InstanceType'], 't4g.small')
        self.assertEqual(host['CreditSpecification'], {'CPUCredits': 'standard'})
        self.assertEqual(host['BlockDeviceMappings'][0]['Ebs'], {'VolumeType': 'gp3', 'VolumeSize': 12, 'Encrypted': True, 'DeleteOnTermination': True})
        self.assertEqual(resources['SecurityGroup']['Properties']['SecurityGroupIngress'], [{'IpProtocol': 'tcp', 'FromPort': 22, 'ToPort': 22, 'CidrIp': {'Ref': 'AdminCidr'}}])
        self.assertFalse(any('DeletionPolicy' in r or 'UpdateReplacePolicy' in r for r in resources.values()))
        self.assertFalse(any(r['Type'] in ['AWS::EC2::EIP', 'AWS::EC2::NatGateway', 'AWS::EC2::Volume', 'AWS::RDS::DBInstance'] for r in resources.values()))

class LifecycleTest(unittest.TestCase):
    def test_failed_creation_autodeletion_ends_wait_immediately(self):
        fake = lambda *args: {'StackSummaries': [{'StackId': 'synthetic-stack', 'StackStatus': 'DELETE_COMPLETE'}]}
        with self.assertRaisesRegex(ValueError, 'Stack failed'):
            cloud.wait_stack(fake, {'stackId': 'synthetic-stack'})
        cloud.wait_stack(fake, {'stackId': 'synthetic-stack'}, deleting=True)

    def test_lost_create_response_recovers_even_after_automatic_delete(self):
        state = {'stackName': 'pink-party-lab-synthetic'}
        def fake(*args):
            self.assertEqual(args[:2], ('cloudformation', 'list-stacks'))
            return {'StackSummaries': [{'StackName': state['stackName'], 'StackId': 'synthetic-id', 'StackStatus': 'DELETE_COMPLETE'}]}
        result = cloud.recover_stack(fake, state)
        self.assertEqual(state['stackId'], 'synthetic-id')
        self.assertEqual(result['StackStatus'], 'DELETE_COMPLETE')

class HostKeyTest(unittest.TestCase):
    def test_console_key_scope_and_duplicates(self):
        import base64
        console = 'ssh-ed25519 OUTSIDE\n-----BEGIN SSH HOST KEY KEYS-----\nssh-ed25519 SYNTHETIC fixture\n-----END SSH HOST KEY KEYS-----\n'
        self.assertEqual(cloud.console_host_key(console), 'ssh-ed25519 SYNTHETIC')
        self.assertEqual(cloud.console_host_key(base64.b64encode(console.encode()).decode()), 'ssh-ed25519 SYNTHETIC')
        for bad in ['ssh-ed25519 OUTSIDE', console.replace('ssh-ed25519 SYNTHETIC fixture', 'ssh-ed25519 ONE\nssh-ed25519 TWO')]:
            with self.assertRaises(ValueError):
                cloud.console_host_key(bad)

class StateTest(unittest.TestCase):
    def test_interrupted_staging_cannot_block_future_state_or_cleanup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.chmod(0o700)
            state = root / 'aws-state.json'
            stale = root / 'aws-state.tmp'
            stale.write_text('interrupted')
            cloud.private_write(state, {'version': 1})
            cloud.private_write(state, {'version': 2})
            self.assertEqual(json.loads(state.read_text()), {'version': 2})
            self.assertEqual(state.stat().st_mode & 0o777, 0o600)
            self.assertEqual(stale.read_text(), 'interrupted')
            with self.assertRaises(TypeError):
                cloud.private_write(state, {'bad': object()})
            self.assertEqual(json.loads(state.read_text()), {'version': 2})
            self.assertFalse(list(root.glob('.aws-state.json-*.tmp')))


class ReadinessTest(unittest.TestCase):
    def test_every_private_unit_must_be_active(self):
        from types import SimpleNamespace
        self.assertTrue(cloud.private_ready(lambda command: SimpleNamespace(returncode=0)))
        for failed in ['service-health.ts', 'pink-party-https.service', 'pink-party-monitor.timer', 'pink-party-backup.timer']:
            self.assertFalse(cloud.private_ready(lambda command: SimpleNamespace(returncode=int(failed in command))))


if __name__ == '__main__':
    unittest.main()

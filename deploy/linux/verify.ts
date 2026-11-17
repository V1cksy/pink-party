import assert from 'node:assert/strict';
import { execFile, spawnSync } from 'node:child_process';
import { readFile, writeFile, mkdir, rm, stat, access } from 'node:fs/promises';
import { promisify } from 'node:util';
import { arch, release } from 'node:os';
import { loadSettings } from '../../server/config.ts';
import { createServer } from 'node:http';
import { healthyService, serviceListener } from './service-health.ts';

const exec = promisify(execFile);
const unit = 'pink-party.service';
const override = '/run/systemd/system/pink-party.service.d/90-exercise.conf';
const invalidEnv = '/run/pink-party-exercise.env';
const lock = '/run/pink-party-verification.lock';
assert.equal(
  process.getuid?.(),
  0,
  'Run this verification with sudo in the VM',
);
assert.equal(process.platform, 'linux');
assert.equal(loadSettings(process.env).privateAccess, undefined);
for (const path of [override, invalidEnv]) {
  await access(path).then(
    () => {
      throw new Error(
        `Existing exercise file: ${path}; inspect it before retrying`,
      );
    },
    (error: NodeJS.ErrnoException) => {
      if (error.code !== 'ENOENT') throw error;
    },
  );
}
await mkdir(lock);
let changedService = false;
let ownsOverride = false;
let ownsInvalidEnv = false;
const report: Record<string, unknown> = {
  capturedAt: new Date().toISOString(),
  scope: 'Automated local Ubuntu VM; no peer-device or human-listening claim',
  checks: {},
  exercises: [],
};
const checks = report.checks as Record<string, boolean>;
const exercises = report.exercises as Record<string, unknown>[];
const command = async (file: string, args: string[]) =>
  (
    await exec(file, args, { timeout: 20_000, maxBuffer: 1024 * 1024 })
  ).stdout.trim();
const property = (name: string) =>
  command('systemctl', ['show', unit, `--property=${name}`, '--value']);
const health = healthyService;
async function until(test: () => Promise<boolean>, label: string) {
  const deadline = Date.now() + 30_000;
  while (Date.now() < deadline) {
    if (await test()) return;
    await new Promise((resolve) => setTimeout(resolve, 200));
  }
  throw new Error(`Timed out: ${label}`);
}
function check(name: string, value: boolean) {
  assert.ok(value, name);
  checks[name] = true;
  console.log(`${name}: OK`);
}
async function socket(port: number, udp = false) {
  return command('ss', ['-H', udp ? '-lunp' : '-ltnp', `sport = :${port}`]);
}
async function assertStopped() {
  assert.equal(await health(), false);
  for (const port of [3000, 7880]) assert.equal(await socket(port), '');
  assert.equal(await socket(7882, true), '');
}
async function crash(port: number, name: string) {
  const before = await property('MainPID');
  const child = await serviceListener(port);
  const started = Date.now();
  process.kill(Number(child), 'SIGKILL');
  await until(
    async () => (await property('MainPID')) !== before && (await health()),
    `${name} crash recovery`,
  );
  assert.throws(() => process.kill(Number(child), 0), { code: 'ESRCH' });
  exercises.push({
    name: `${name} SIGKILL: supervisor exits and systemd starts a healthy replacement`,
    passed: true,
    recoveryMs: Date.now() - started,
  });
  console.log(`${name} crash recovery: OK`);
}

try {
  report.environment = {
    os: (await readFile('/etc/os-release', 'utf8')).match(
      /^PRETTY_NAME="(.*)"$/m,
    )?.[1],
    architecture: arch(),
    kernel: release(),
    node: process.version,
    livekit: await command('/opt/pink-party/bin/livekit-server', ['--version']),
    systemd: (await command('systemctl', ['--version'])).split('\n')[0],
  };
  await until(health, 'initial health');
  check(
    'enabledAtGuestBoot',
    (await command('systemctl', ['is-enabled', unit])) === 'enabled',
  );
  check('dedicatedServiceUser', (await property('User')) === 'pink-party');
  const uid = Number(await command('id', ['-u', 'pink-party']));
  check('nonRootUid', uid > 0);
  const status = await readFile(
    `/proc/${await property('MainPID')}/status`,
    'utf8',
  );
  check(
    'effectiveUidMatches',
    Number(status.match(/^Uid:\s+\d+\s+(\d+)/m)?.[1]) === uid,
  );
  check('noEffectiveCapabilities', /^CapEff:\s+0+$/m.test(status));
  check('noNewPrivileges', /^NoNewPrivs:\s+1$/m.test(status));
  check('systemFilesReadOnly', (await property('ProtectSystem')) === 'strict');
  check('homeDirectoriesHidden', (await property('ProtectHome')) === 'yes');
  const envStat = await stat('/etc/pink-party/pink-party.env');
  check(
    'credentialsRootOnly',
    envStat.uid === 0 && (envStat.mode & 0o777) === 0o600,
  );
  const stateStat = await stat('/var/lib/pink-party');
  check(
    'stateOwnerAndMode',
    stateStat.uid === uid && (stateStat.mode & 0o777) === 0o700,
  );
  const configStat = await stat('/var/lib/pink-party/livekit.yaml');
  check(
    'generatedConfigOwnerAndMode',
    configStat.uid === uid && (configStat.mode & 0o777) === 0o600,
  );
  for (const path of [
    '/opt/pink-party/app/server/index.ts',
    '/opt/pink-party/app/data/session.json',
    '/etc/pink-party/pink-party.env',
  ]) {
    check(
      `serviceCannotWrite:${path}`,
      spawnSync('runuser', ['-u', 'pink-party', '--', 'test', '-w', path])
        .status === 1,
    );
  }
  check(
    'serviceCanWriteState',
    spawnSync('runuser', [
      '-u',
      'pink-party',
      '--',
      'test',
      '-w',
      '/var/lib/pink-party',
    ]).status === 0,
  );
  for (const [port, udp] of [
    [3000, false],
    [7880, false],
    [7882, true],
  ] as const) {
    const lines = await socket(port, udp);
    check(
      `loopbackOnly:${udp ? 'udp' : 'tcp'}:${port}`,
      lines.length > 0 &&
        lines
          .split('\n')
          .every((line) => line.split(/\s+/)[3] === `127.0.0.1:${port}`),
    );
  }
  const resources = [];
  for (let sample = 0; sample < 10; sample++) {
    resources.push(Number(await property('MemoryCurrent')));
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  report.idleResources = {
    samples: resources.length,
    intervalSeconds: 1,
    meanServiceMemoryMiB: +(
      resources.reduce((a, b) => a + b, 0) /
      resources.length /
      1024 ** 2
    ).toFixed(2),
    peakServiceMemoryMiB: +(Math.max(...resources) / 1024 ** 2).toFixed(2),
    scope:
      'systemd cgroup: supervisor, app, LiveKit and charged cache; excludes VM, SSH, browser and test runner',
  };
  changedService = true;
  await crash(3000, 'application');
  await crash(7880, 'LiveKit');
  await command('systemctl', ['stop', unit]);
  await new Promise((resolve) => setTimeout(resolve, 3000));
  await assertStopped();
  check(
    'manualStopReleasesSocketsAndStaysStopped',
    (await property('ActiveState')) === 'inactive',
  );

  const foreign = createServer((_request, response) => response.end('{}'));
  await new Promise<void>((resolve, reject) => {
    foreign.once('error', reject);
    foreign.listen(3000, '127.0.0.1', resolve);
  });
  try {
    assert.equal(await health(), false);
    await assert.rejects(
      () => serviceListener(3000),
      /not owned by pink-party.service/,
    );
    check('foreignHttpListenerIsRejectedBeforeAnyKill', true);
  } finally {
    await new Promise<void>((resolve, reject) =>
      foreign.close((error) => (error ? reject(error) : resolve())),
    );
  }

  await mkdir('/run/systemd/system/pink-party.service.d', { recursive: true });
  const env = await readFile('/etc/pink-party/pink-party.env', 'utf8');
  await writeFile(
    invalidEnv,
    env.replace(/^LIVEKIT_API_SECRET=.*$/m, 'LIVEKIT_API_SECRET=invalid'),
    { mode: 0o600, flag: 'wx' },
  );
  ownsInvalidEnv = true;
  await writeFile(
    override,
    `[Service]\nRestart=no\nEnvironmentFile=\nEnvironmentFile=${invalidEnv}\n`,
    { mode: 0o600, flag: 'wx' },
  );
  ownsOverride = true;
  await command('systemctl', ['daemon-reload']);
  await command('systemctl', ['start', unit]);
  await until(
    async () => (await property('ActiveState')) === 'failed',
    'invalid configuration rejection',
  );
  await assertStopped();
  const invocation = await property('InvocationID');
  const log = await command('journalctl', [
    `_SYSTEMD_INVOCATION_ID=${invocation}`,
    '--output=cat',
    '--no-pager',
  ]);
  check(
    'invalidConfigurationHasUsefulJournalDiagnostic',
    log.includes('Missing or invalid secrets.'),
  );
  check(
    'invalidConfigurationDoesNotLogSecrets',
    !log.includes(process.env.LIVEKIT_API_SECRET!) &&
      !log.includes(process.env.JOIN_CODE!),
  );
  exercises.push({
    name: 'invalid credentials: startup rejected, sockets closed, cause identified in journal',
    passed: true,
  });
} catch (error) {
  report.failure =
    error instanceof Error ? error.message : 'Verification failed';
  process.exitCode = 1;
} finally {
  const cleanupErrors: string[] = [];
  async function clean(label: string, action: () => Promise<unknown>) {
    try {
      await action();
    } catch {
      cleanupErrors.push(label);
      process.exitCode = 1;
    }
  }
  if (changedService) {
    await clean('stop service', () => command('systemctl', ['stop', unit]));
    if (ownsOverride)
      await clean('remove exercise override', () =>
        rm(override, { force: true }),
      );
    if (ownsInvalidEnv)
      await clean('remove exercise credentials', () =>
        rm(invalidEnv, { force: true }),
      );
    await clean('reload units', () => command('systemctl', ['daemon-reload']));
    await clean('reset failure state', () =>
      command('systemctl', ['reset-failed', unit]),
    );
    await clean('start normal service', () =>
      command('systemctl', ['start', unit]),
    );
    await clean('wait for normal health', () =>
      until(health, 'restored normal configuration'),
    );
    report.normalServiceRestored = cleanupErrors.length === 0;
  }
  if (cleanupErrors.length) report.cleanupErrors = cleanupErrors;
  await clean('write verification report', () =>
    writeFile(
      '/var/lib/pink-party/linux-validation.json',
      JSON.stringify(report, null, 2) + '\n',
      { mode: 0o600 },
    ),
  );
  await clean('release verification lock', () => rm(lock, { recursive: true }));
  console.log(
    process.exitCode
      ? `FAILED: ${report.failure ?? cleanupErrors.join(', ')}`
      : 'Linux service verification passed; normal service restored.',
  );
}

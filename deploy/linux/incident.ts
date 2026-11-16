import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { mkdir, rm, writeFile } from 'node:fs/promises';
import { promisify } from 'node:util';
import { loadSettings } from '../../server/config.ts';
import { healthyService } from './service-health.ts';
import { readHistory } from './monitor.ts';
import type { MonitorSample } from './monitor.ts';

const exec = promisify(execFile);
const unit = 'pink-party.service';
const timer = 'pink-party-monitor.timer';
const directory = '/var/lib/pink-party-monitor';
// Share the destructive verifier's lock: service exercises must run sequentially.
const lock = '/run/pink-party-verification.lock';
assert.equal(process.getuid?.(), 0, 'Run with sudo in the Linux VM');
assert.equal(process.platform, 'linux');
assert.equal(loadSettings(process.env).privateAccess, undefined);
const command = async (file: string, args: string[]) =>
  (
    await exec(file, args, { timeout: 20_000, maxBuffer: 1024 * 1024 })
  ).stdout.trim();
const property = (target: string, name: string) =>
  command('systemctl', ['show', target, `--property=${name}`, '--value']);
const now = () => new Date().toISOString();
async function until<T>(read: () => Promise<T | undefined>, label: string) {
  const deadline = performance.now() + 75_000;
  while (performance.now() < deadline) {
    const result = await read();
    if (result !== undefined) return result;
    await new Promise((resolve) => setTimeout(resolve, 500));
  }
  throw new Error(`Timed out: ${label}`);
}
async function scheduled(status: 'up' | 'down', after: string) {
  return until(
    async () =>
      (await readHistory()).find(
        (sample) => sample.observedAt > after && sample.status === status,
      ),
    `scheduled ${status} observation`,
  );
}
const report: Record<string, unknown> = {
  scope:
    'Codex-run controlled local VM outage; web/control only; synthetic data',
  startedAt: now(),
  fault: 'Explicit systemctl stop; no configuration or credential change',
};
const timeline: Record<string, string> = {};
report.timeline = timeline;
let changed = false;
await mkdir(lock);
try {
  assert.equal(await command('systemctl', ['is-enabled', timer]), 'enabled');
  assert.equal(await property(timer, 'ActiveState'), 'active');
  assert.ok(await healthyService(), 'Service must start healthy');
  const baseline = await scheduled('up', now());
  timeline.baselineObservedAt = baseline.observedAt;
  timeline.stopRequestedAt = now();
  changed = true;
  await command('systemctl', ['stop', unit]);
  timeline.stopCompletedAt = now();
  const down: MonitorSample = await scheduled('down', timeline.stopRequestedAt);
  timeline.downObservedAt = down.observedAt;
  assert.equal(down.reason, 'service-not-active');
  const state = await property(unit, 'ActiveState');
  assert.equal(state, 'inactive');
  assert.equal(await property(unit, 'MainPID'), '0');
  assert.equal(await property(timer, 'ActiveState'), 'active');
  for (const [flag, port] of [
    ['-ltnp', 3000],
    ['-ltnp', 7880],
    ['-lunp', 7882],
  ] as const)
    assert.equal(await command('ss', ['-H', flag, `sport = :${port}`]), '');
  const journal = await command('journalctl', [
    '-u',
    unit,
    '--since',
    timeline.stopRequestedAt,
    '--no-pager',
    '-o',
    'short-iso-precise',
  ]);
  assert.match(journal, /Stopped pink-party\.service/);
  await writeFile(`${directory}/incident-service.log`, journal + '\n', {
    mode: 0o600,
  });
  timeline.diagnosedAt = now();
  report.diagnosis = {
    serviceState: state,
    mainProcessAbsent: true,
    socketsAbsent: true,
    monitorTimerStillActive: true,
    journalConfirmsExplicitStop: true,
    configurationChanged: false,
  };
  console.log(
    'Scheduled monitor detected the outage; inactive unit, absent sockets and stop journal confirmed.',
  );
  timeline.startRequestedAt = now();
  await command('systemctl', ['start', unit]);
  await until(
    async () => ((await healthyService()) ? true : undefined),
    'restored health',
  );
  timeline.healthVerifiedAt = now();
  const up = await scheduled('up', timeline.startRequestedAt);
  timeline.recoveryObservedAt = up.observedAt;
  report.observations = { baseline, down, recovery: up };
  const milliseconds = (end: string, start: string) =>
    Date.parse(end) - Date.parse(start);
  report.timingMs = {
    detectionAfterStopRequested: milliseconds(
      down.observedAt,
      timeline.stopRequestedAt,
    ),
    healthAfterStartRequested: milliseconds(
      timeline.healthVerifiedAt,
      timeline.startRequestedAt,
    ),
    recoveryObservationAfterStartRequested: milliseconds(
      up.observedAt,
      timeline.startRequestedAt,
    ),
    observedDownToUp: milliseconds(up.observedAt, down.observedAt),
    stopCompletedToHealthy: milliseconds(
      timeline.healthVerifiedAt,
      timeline.stopCompletedAt,
    ),
  };
  report.passed = true;
} catch (error) {
  report.passed = false;
  // Detailed command errors may contain private journal output; keep them local.
  await writeFile(`${directory}/incident-error.log`, String(error) + '\n', {
    mode: 0o600,
  });
  console.error(
    'Incident exercise failed; inspect private incident-error.log.',
  );
  process.exitCode = 1;
} finally {
  try {
    if (changed) {
      await command('systemctl', ['start', unit]);
      await until(
        async () => ((await healthyService()) ? true : undefined),
        'cleanup health',
      );
    }
    report.normalServiceRestored = await healthyService();
    if (!report.normalServiceRestored) process.exitCode = 1;
  } catch {
    report.normalServiceRestored = false;
    process.exitCode = 1;
  }
  try {
    await writeFile(
      `${directory}/incident.json`,
      JSON.stringify(report, null, 2) + '\n',
      { mode: 0o600 },
    );
  } finally {
    await rm(lock, { recursive: true });
  }
}
console.log(
  process.exitCode
    ? 'Exercise incomplete; inspect private reports.'
    : 'Scheduled outage and recovery exercise passed; normal service restored.',
);

import { readFile, rename, stat, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { inspectServiceHealth } from './service-health.ts';
import type { HealthObservation } from './service-health.ts';

export const historyLimit = 2880;
const historyPath = '/var/lib/pink-party-monitor/history.json';
export type MonitorSample = HealthObservation & {
  observedAt: string;
  durationMs: number;
  media: 'not-tested';
};

function retainSamples(
  history: MonitorSample[],
  sample: MonitorSample,
): MonitorSample[] {
  return [...history.slice(-(historyLimit - 1)), sample];
}

export async function readHistory(
  path = historyPath,
): Promise<MonitorSample[]> {
  let text: string;
  try {
    if ((await stat(path)).size > 1024 * 1024)
      throw new Error('Monitor history too large');
    text = await readFile(path, 'utf8');
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code === 'ENOENT') return [];
    throw error;
  }
  if (text.length > 1024 * 1024) throw new Error('Monitor history too large');
  const value: unknown = JSON.parse(text);
  const reasons = [
    'web-control-ready',
    'service-not-active',
    'service-query-failed',
    'listener-not-owned',
    'health-request-failed',
  ];
  if (
    !Array.isArray(value) ||
    value.length > historyLimit ||
    !value.every(
      (row) =>
        row &&
        Object.keys(row).sort().join(',') ===
          'durationMs,media,observedAt,reason,status' &&
        ['up', 'down'].includes(row.status) &&
        reasons.includes(row.reason) &&
        typeof row.observedAt === 'string' &&
        new Date(row.observedAt).toISOString() === row.observedAt &&
        Number.isFinite(row.durationMs) &&
        row.durationMs >= 0 &&
        row.media === 'not-tested',
    )
  )
    throw new Error('Invalid monitor history; inspect the private state file');
  return value;
}

export async function runMonitor(
  path = historyPath,
  inspect = inspectServiceHealth,
) {
  const history = await readHistory(path);
  const started = performance.now();
  const health = await inspect();
  const sample: MonitorSample = {
    observedAt: new Date().toISOString(),
    ...health,
    durationMs: Math.round(performance.now() - started),
    media: 'not-tested',
  };
  const temporary = path + '.tmp';
  await writeFile(
    temporary,
    JSON.stringify(retainSamples(history, sample)) + '\n',
    {
      mode: 0o600,
    },
  );
  await rename(temporary, path);
  const previous = history.at(-1);
  if (previous?.status !== sample.status || previous?.reason !== sample.reason)
    console.log(
      JSON.stringify({ ...sample, previous: previous?.status ?? 'unknown' }),
    );
  // A recorded outage is a successful observation. Execution/storage errors fail the unit.
  return sample;
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  try {
    await runMonitor();
  } catch {
    console.error(
      'Monitor failed to record health; inspect its unit and private history.',
    );
    process.exitCode = 1;
  }
}

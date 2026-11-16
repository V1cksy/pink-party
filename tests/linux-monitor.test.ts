import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtemp, readFile, rm, stat, writeFile } from 'node:fs/promises';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { inspectServiceHealth } from '../deploy/linux/service-health.ts';
import {
  historyLimit,
  readHistory,
  runMonitor,
} from '../deploy/linux/monitor.ts';
import type { MonitorSample } from '../deploy/linux/monitor.ts';

test('Linux health distinguishes stopped service, foreign listeners and failed control health', async () => {
  const tools = {
    activeState: async () => 'inactive',
    listener: async (_port: number) => {
      throw new Error('foreign fixture');
    },
    request: async () => Response.json({ status: 'ok', voice: 'ready' }),
  };
  assert.deepEqual(await inspectServiceHealth(tools), {
    status: 'down',
    reason: 'service-not-active',
  });
  tools.activeState = async () => 'active';
  assert.deepEqual(await inspectServiceHealth(tools), {
    status: 'down',
    reason: 'listener-not-owned',
  });
  const ownedTools = { ...tools, listener: async () => 42 };
  assert.equal((await inspectServiceHealth(ownedTools)).status, 'up');
  assert.equal(
    (
      await inspectServiceHealth({
        ...ownedTools,
        listener: async (port) => {
          if (port === 7880) throw new Error('foreign control listener');
          return 42;
        },
      })
    ).reason,
    'listener-not-owned',
  );
  for (const response of [
    Response.json(
      { status: 'degraded', voice: 'unavailable' },
      { status: 503 },
    ),
    Response.json({}),
  ]) {
    assert.deepEqual(
      await inspectServiceHealth({
        ...ownedTools,
        request: async () => response,
      }),
      { status: 'down', reason: 'health-request-failed' },
    );
  }
  assert.equal(
    (
      await inspectServiceHealth({
        ...ownedTools,
        request: async () => {
          throw new Error('timeout/private response');
        },
      })
    ).reason,
    'health-request-failed',
  );
  assert.equal(
    (
      await inspectServiceHealth({
        ...ownedTools,
        activeState: async () => {
          throw new Error('systemctl failure');
        },
      })
    ).reason,
    'service-query-failed',
  );
});

test('Monitor keeps bounded outage/recovery history without treating health as media reception', async (t) => {
  const dir = await mkdtemp(join(tmpdir(), 'pink-party-monitor-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const path = join(dir, 'history.json');
  assert.deepEqual(await readHistory(path), []);
  for (const status of ['up', 'down', 'down', 'up'] as const)
    await runMonitor(path, async () => ({
      status,
      reason: status === 'up' ? 'web-control-ready' : 'service-not-active',
    }));
  const history = await readHistory(path);
  assert.deepEqual(
    history.map((row) => row.status),
    ['up', 'down', 'down', 'up'],
  );
  assert.ok(history.every((row) => row.media === 'not-tested'));
  assert.equal((await stat(path)).mode & 0o777, 0o600);
  const oldest = {
    ...history[0],
    observedAt: '2026-11-16T00:00:00.000Z',
  } satisfies MonitorSample;
  await writeFile(
    path,
    JSON.stringify([
      oldest,
      ...Array.from({ length: historyLimit - 1 }, () => history[0]),
    ]),
  );
  const latest = await runMonitor(path, async () => ({
    status: 'up',
    reason: 'web-control-ready',
  }));
  const bounded = await readHistory(path);
  assert.equal(bounded.length, historyLimit);
  assert.deepEqual(bounded.at(-1), latest);
  assert.ok(!bounded.some((row) => row.observedAt === oldest.observedAt));
  await writeFile(path, 'invalid');
  await assert.rejects(() => runMonitor(path));
  assert.equal(
    await readFile(path, 'utf8'),
    'invalid',
    'Corrupt evidence must not be silently overwritten',
  );
});

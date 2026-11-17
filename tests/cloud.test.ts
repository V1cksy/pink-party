import assert from 'node:assert/strict';
import { test } from 'node:test';
import { deviceFromStatus } from '../scripts/tailscale.ts';
import {
  monitorHeaders,
  requestHealth,
} from '../deploy/linux/health-request.ts';
import { createServer } from 'node:http';
import { readRemoteTarget } from '../deploy/cloud/target.ts';
import { mkdtemp, writeFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

test('Tagged server discovery does not require a user identity; disconnected nodes fail closed', () => {
  const state = {
    BackendState: 'Running',
    Self: {
      Online: true,
      DNSName: 'cloud.example-tail.ts.net.',
      TailscaleIPs: ['100.100.100.100'],
      Tags: ['tag:lab'],
    },
  };
  assert.deepEqual(deviceFromStatus(state), {
    origin: 'https://cloud.example-tail.ts.net',
    ip: '100.100.100.100',
  });
  for (const bad of [
    { ...state, BackendState: 'NeedsLogin' },
    { ...state, Self: { ...state.Self, Online: false } },
    { ...state, Self: { ...state.Self, TailscaleIPs: [] } },
  ])
    assert.throws(() => deviceFromStatus(bad));
});

test('Local monitor validates its private Host/login without loading application secrets', () => {
  const valid = {
    origin: 'https://cloud.example-tail.ts.net',
    login: 'peach@example.com',
  };
  assert.deepEqual(monitorHeaders(valid), {
    Host: 'cloud.example-tail.ts.net',
    'Tailscale-User-Login': 'peach@example.com',
  });
  for (const value of [
    null,
    {},
    { ...valid, origin: 'http://evil.example' },
    { ...valid, origin: 'https://cloud.example-tail.ts.net:443' },
    { ...valid, login: 'peach@example.com\r\nInjected: true' },
    { ...valid, login: 'peach@example.com,berry@example.com' },
    { ...valid, LIVEKIT_API_SECRET: 'unexpected' },
  ])
    assert.throws(() => monitorHeaders(value));
});

test('Private health request sends the exact Host and login over a real loopback socket', async (t) => {
  const headers = monitorHeaders({
    origin: 'https://cloud.example-tail.ts.net',
    login: 'peach@example.com',
  });
  const server = createServer((req, res) => {
    const accepted =
      req.headers.host === headers.Host &&
      req.headers['tailscale-user-login'] === headers['Tailscale-User-Login'];
    res.writeHead(accepted ? 200 : 403, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ status: 'ok', voice: 'ready' }));
  });
  t.after(() => {
    server.closeAllConnections();
    server.close();
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  if (!address || typeof address === 'string')
    throw new Error('No fixture address');
  const response = await requestHealth(headers, address.port);
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), { status: 'ok', voice: 'ready' });
});

test('Health request rejects oversized or stalled HTTP responses within its deadline', async (t) => {
  const server = createServer((req, res) => {
    if (req.headers['x-fixture'] === 'large') res.end('x'.repeat(4096));
    else res.writeHead(200);
  });
  t.after(() => {
    server.closeAllConnections();
    server.close();
  });
  await new Promise<void>((resolve) => server.listen(0, '127.0.0.1', resolve));
  const address = server.address();
  if (!address || typeof address === 'string')
    throw new Error('No fixture address');
  await assert.rejects(
    requestHealth({ 'x-fixture': 'large' }, address.port),
    /size limit/,
  );
  await assert.rejects(requestHealth({}, address.port));
});

test('Remote target accepts only the HTTPS origin and private media address', async (t) => {
  const directory = await mkdtemp(join(tmpdir(), 'pink-party-target-'));
  t.after(() => rm(directory, { recursive: true, force: true }));
  const path = join(directory, 'target.json');
  const valid = {
    origin: 'https://cloud.example-tail.ts.net',
    tailscaleIp: '100.100.100.100',
  };
  await writeFile(path, JSON.stringify(valid));
  const result = await readRemoteTarget(path);
  assert.equal(result.origin, valid.origin);
  assert.equal(result.tailscaleIp, valid.tailscaleIp);
  for (const bad of [
    null,
    { ...valid, apiSecret: 'unexpected' },
    { ...valid, origin: 'http://evil.example' },
    { ...valid, tailscaleIp: '0.0.0.0' },
  ]) {
    await writeFile(path, JSON.stringify(bad));
    await assert.rejects(readRemoteTarget(path));
  }
});

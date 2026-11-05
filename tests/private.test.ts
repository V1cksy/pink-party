import assert from 'node:assert/strict';
import { test } from 'node:test';
import { request, type IncomingMessage } from 'node:http';
import { TokenVerifier } from 'livekit-server-sdk';
import { checkAccess } from '../server/access.ts';
import { loadSettings, livekitConfig } from '../server/config.ts';
import { issueVoiceToken } from '../server/admission.ts';
import { createApp } from '../server/app.ts';
import { readSession } from '../server/session.ts';
import { assertServePortFree } from '../scripts/tailscale.ts';
const local = {
  joinCode: 'synthetic-local-code',
  apiKey: 'synthetic-api-key',
  apiSecret: 'synthetic-test-secret-at-least-32-characters',
};

const env = {
  PINK_PARTY_MODE: 'private',
  PUBLIC_ORIGIN: 'https://hangout.example-tail.ts.net',
  TAILSCALE_IP: '100.100.100.100',
  INVITED_LOGINS: 'peach@example.com,berry@example.com',
  LIVEKIT_API_KEY: local.apiKey,
  LIVEKIT_API_SECRET: local.apiSecret,
};
const settings = loadSettings(env);
const origin = env.PUBLIC_ORIGIN;
const host = new URL(origin).host;
const voice = {
  createRoom: async () => ({}),
  listParticipants: async () => [],
};
function incoming(headers: Record<string, string>, ip = '127.0.0.1') {
  return { headers, socket: { remoteAddress: ip } } as IncomingMessage;
}

test('identity is exact, invited, loopback-only, and separate from local development admission', () => {
  const headers = { host, origin, 'tailscale-user-login': 'peach@example.com' };
  assert.equal(checkAccess(incoming(headers), settings), 'peach@example.com');
  for (const login of [
    '',
    'stranger@example.com',
    'Peach@example.com',
    'peach@example.com,berry@example.com',
  ])
    assert.throws(() =>
      checkAccess(
        incoming({ ...headers, 'tailscale-user-login': login }),
        settings,
      ),
    );
  assert.throws(() => checkAccess(incoming({ host, origin }), settings));
  for (const ip of [
    '100.100.100.101',
    '192.168.1.10',
    '::1',
    '::ffff:127.0.0.1',
  ])
    assert.throws(() => checkAccess(incoming(headers, ip), settings));
  for (const badHost of [
    'localhost:3000',
    '127.0.0.1:3000',
    'evil.example',
    host + ':443',
  ])
    assert.throws(() =>
      checkAccess(incoming({ ...headers, host: badHost }), settings),
    );
  for (const badOrigin of [
    'http://localhost:3000',
    origin + '.evil.example',
    'null',
  ])
    assert.throws(() =>
      checkAccess(incoming({ ...headers, origin: badOrigin }), settings),
    );
  assert.throws(() =>
    checkAccess(
      incoming({
        host: 'localhost:3000',
        'tailscale-user-login': 'peach@example.com',
      }),
      local,
    ),
  );
  assert.throws(() =>
    checkAccess(
      incoming({ host: 'localhost:3000', 'x-forwarded-host': host }),
      local,
    ),
  );
  assert.equal(
    checkAccess(incoming({ host: 'localhost:3000' }), local),
    undefined,
  );
});

test('private config fails closed and generates only the intended media address', () => {
  for (const patch of [
    { JOIN_CODE: local.joinCode },
    { INVITED_LOGINS: '' },
    { INVITED_LOGINS: '*' },
    { PUBLIC_ORIGIN: 'https://evil.example' },
    { PUBLIC_ORIGIN: origin + '/' },
    { PUBLIC_ORIGIN: origin + ':8443' },
    { TAILSCALE_IP: '192.168.1.10' },
    { TAILSCALE_IP: '100.100.100.999' },
    { PINK_PARTY_MODE: 'remote' },
    { PINK_PARTY_MODE: 'local', JOIN_CODE: local.joinCode },
  ])
    assert.throws(() => loadSettings({ ...env, ...patch }));
  const config = livekitConfig(settings);
  assert.match(config, /bind_addresses: \[127.0.0.1\]/);
  assert.match(config, /node_ip: 100.100.100.100/);
  assert.match(config, /includes: \[100.100.100.100\/32\]/);
  assert.match(config, /enable_loopback_candidate: false/);
  assert.match(config, /tcp_port: 0/);
  assert.match(config, /stun_servers: \[\]/);
});

test('private admission requires verified identity, ignores development code, preserves token restrictions and cap', async () => {
  const body = { displayName: 'Peach', joinCode: local.joinCode };
  await assert.rejects(issueVoiceToken(body, settings, voice));
  await assert.rejects(
    issueVoiceToken(body, settings, voice, 'stranger@example.com'),
  );
  const result = await issueVoiceToken(
    { displayName: 'Peach' },
    settings,
    voice,
    'peach@example.com',
  );
  assert.equal(result.url, origin.replace('https:', 'wss:') + '/livekit');
  const claims = await new TokenVerifier(
    settings.apiKey,
    settings.apiSecret,
  ).verify(result.token);
  assert.equal(claims.video?.room, 'pink-party');
  assert.deepEqual(claims.video?.canPublishSources, ['microphone']);
  assert.equal(claims.video?.canPublishData, false);
  assert.equal(claims.video?.canUpdateOwnMetadata, false);
  assert.ok(claims.exp! - Date.now() / 1000 <= 60);
  assert.ok(claims.exp! - Date.now() / 1000 > 57);
  await assert.rejects(
    issueVoiceToken(
      body,
      settings,
      { ...voice, listParticipants: async () => Array(4).fill({}) },
      'peach@example.com',
    ),
    (e: unknown) => (e as { status: number }).status === 409,
  );
});

test('HTTP and WebSocket entry points both enforce private host, origin and identity (injected headers)', async (t) => {
  const app = createApp({
    settings,
    voice,
    session: await readSession(),
    health: async () => {},
  });
  await new Promise<void>((resolve) => app.listen(0, '127.0.0.1', resolve));
  t.after(() => {
    app.closeAllConnections();
    app.close();
  });
  const address = app.address();
  assert.ok(address && typeof address === 'object');
  const send = (
    path: string,
    headers: Record<string, string> = {},
    method = 'GET',
    body?: string,
  ) =>
    new Promise<{ status: number; body: string; csp: string }>(
      (resolve, reject) => {
        const req = request(
          {
            host: '127.0.0.1',
            port: address.port,
            path,
            method,
            headers: { Host: host, ...headers },
          },
          (res) => {
            let data = '';
            res.on('data', (chunk) => (data += chunk));
            res.on('end', () =>
              resolve({
                status: res.statusCode!,
                body: data,
                csp: String(res.headers['content-security-policy'] ?? ''),
              }),
            );
          },
        );
        req.on('error', reject);
        req.end(body);
      },
    );
  const identity = { 'Tailscale-User-Login': 'peach@example.com' };
  assert.equal((await send('/api/session')).status, 403);
  assert.equal(
    (await send('/api/session', { ...identity, Host: 'localhost:3000' }))
      .status,
    403,
  );
  assert.equal(
    (
      await send('/api/session', {
        'Tailscale-User-Login': 'stranger@example.com',
      })
    ).status,
    403,
  );
  assert.equal(
    (await send('/api/access', identity)).body,
    '{"mode":"private"}',
  );
  const granted = await send(
    '/api/voice-token',
    { ...identity, Origin: origin, 'Content-Type': 'application/json' },
    'POST',
    '{"displayName":"Peach"}',
  );
  assert.equal(granted.status, 200);
  assert.ok(granted.csp.includes('wss://hangout.example-tail.ts.net/livekit'));
  assert.ok(!granted.csp.includes('ws://127.0.0.1'));
  assert.equal(
    (
      await send(
        '/api/voice-token',
        { Origin: origin, 'Content-Type': 'application/json' },
        'POST',
        JSON.stringify({ displayName: 'Peach', joinCode: local.joinCode }),
      )
    ).status,
    403,
  );
  assert.equal((await send('/api/voice-token', identity, 'POST')).status, 403);
  const upgrade = {
    Connection: 'Upgrade',
    Upgrade: 'websocket',
    'Sec-WebSocket-Version': '13',
    'Sec-WebSocket-Key': 'c3ludGhldGljLWtleS0xMg==',
    Origin: origin,
  };
  assert.equal((await send('/livekit/rtc', upgrade)).status, 403);
  assert.equal(
    (
      await send('/livekit/rtc', {
        ...upgrade,
        ...identity,
        Origin: 'http://localhost:3000',
      })
    ).status,
    403,
  );
  assert.equal(
    (await send('/livekit/twirp/livekit.RoomService/DeleteRoom', identity))
      .status,
    404,
  );
});

test('Serve setup preserves conflicting services and rejects Funnel without resetting policy/configuration', () => {
  assert.doesNotThrow(() =>
    assertServePortFree({ TCP: { '8443': {} }, Web: { 'example:8443': {} } }),
  );
  for (const config of [
    { TCP: { '443': {} } },
    { Web: { 'example:443': {} } },
    { AllowFunnel: { 'example:8443': true } },
    { Foreground: { other: { TCP: { '443': {} } } } },
  ])
    assert.throws(() => assertServePortFree(config));
});

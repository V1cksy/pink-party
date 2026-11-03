import assert from 'node:assert/strict';
import { test } from 'node:test';
import { request as httpRequest } from 'node:http';
import { createApp } from '../server/app.ts';
import { readSession } from '../server/session.ts';

const settings = {
  joinCode: 'synthetic-local-code',
  apiKey: 'synthetic-api-key',
  apiSecret: 'synthetic-test-secret-at-least-32-characters',
};

test('HTTP boundary checks host, origin, content type, payload size, rate, health and session data', async (t) => {
  let available = true;
  const app = createApp({
    settings,
    voice: { createRoom: async () => ({}), listParticipants: async () => [] },
    session: await readSession(),
    health: async () => {
      if (!available) throw new Error('down');
    },
  });
  await new Promise<void>((resolve) => app.listen(0, '127.0.0.1', resolve));
  t.after(() => {
    app.closeAllConnections();
    app.close();
  });
  const address = app.address();
  if (!address || typeof address === 'string')
    throw new Error('Expected TCP address');
  const base = `http://127.0.0.1:${address.port}`;
  const request = (path: string, init: RequestInit = {}): Promise<Response> =>
    new Promise((resolve, reject) => {
      const req = httpRequest(
        base + path,
        {
          method: init.method ?? 'GET',
          headers: {
            Host: 'localhost:3000',
            ...(init.headers as Record<string, string>),
          },
        },
        (res) => {
          const chunks: Buffer[] = [];
          res.on('data', (chunk) => chunks.push(chunk));
          res.on('end', () =>
            resolve(
              new Response(Buffer.concat(chunks), {
                status: res.statusCode,
                headers: res.headers as Record<string, string>,
              }),
            ),
          );
        },
      );
      req.on('error', reject);
      req.end(init.body);
    });
  assert.equal((await request('/api/health')).status, 200);
  available = false;
  assert.deepEqual(await (await request('/api/health')).json(), {
    status: 'degraded',
    voice: 'unavailable',
  });
  assert.equal((await request('/api/session')).status, 200);
  assert.equal((await (await request('/api/session')).json()).synthetic, true);
  assert.equal((await request('/.env')).status, 404);
  assert.equal(
    (await request('/api/session', { headers: { Host: 'evil.example' } }))
      .status,
    403,
  );
  const post = (
    body: string,
    origin = 'http://localhost:3000',
    contentType = 'application/json',
  ) =>
    request('/api/voice-token', {
      method: 'POST',
      headers: { Origin: origin, 'Content-Type': contentType },
      body,
    });
  assert.equal((await post('{}', 'https://evil.example')).status, 403);
  assert.equal(
    (await request('/api/voice-token', { method: 'POST' })).status,
    403,
  );
  assert.equal((await post('{}', undefined, 'text/plain')).status, 415);
  assert.equal((await post('{')).status, 400);
  assert.equal((await post('x'.repeat(2100))).status, 413);
  assert.equal(
    (await post(JSON.stringify({ displayName: 'Peach', joinCode: 'wrong' })))
      .status,
    403,
  );
  const tokenResponse = await post(
    JSON.stringify({ displayName: 'Peach', joinCode: settings.joinCode }),
  );
  assert.equal(tokenResponse.status, 200);
  assert.equal(tokenResponse.headers.get('cache-control'), 'no-store');
  assert.ok(
    tokenResponse.headers
      .get('content-security-policy')
      ?.includes("frame-ancestors 'none'"),
  );
  assert.equal(typeof (await tokenResponse.json()).token, 'string');
  let last = tokenResponse;
  for (let i = 0; i < 60; i++) last = await post('{}');
  assert.equal(last.status, 429);
});

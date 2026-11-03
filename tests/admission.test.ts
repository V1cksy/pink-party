import assert from 'node:assert/strict';
import { test } from 'node:test';
import { TokenVerifier } from 'livekit-server-sdk';
import {
  validateAdmission,
  issueVoiceToken,
  HttpError,
} from '../server/admission.ts';
import { loadSettings, TOKEN_TTL_SECONDS } from '../server/config.ts';

export const settings = {
  joinCode: 'synthetic-local-code',
  apiKey: 'synthetic-api-key',
  apiSecret: 'synthetic-test-secret-at-least-32-characters',
};
const body = { displayName: '  Peach ♡  ', joinCode: settings.joinCode };
const voice = {
  createRoom: async () => ({}),
  listParticipants: async () => [],
};

test('admission trims names, preserves Unicode, rejects malformed or unsafe names and wrong codes', () => {
  assert.equal(validateAdmission(body, settings.joinCode), 'Peach ♡');
  for (const invalid of [
    null,
    [],
    {},
    { ...body, displayName: 12 },
    { ...body, displayName: '   ' },
    { ...body, displayName: 'a'.repeat(33) },
    { ...body, displayName: '<script>' },
    { ...body, displayName: 'a\u0000b' },
    { ...body, displayName: 'a\u202eb' },
  ]) {
    assert.throws(
      () => validateAdmission(invalid, settings.joinCode),
      (e: unknown) => e instanceof HttpError && e.status === 400,
    );
  }
  for (const joinCode of ['', 'wrong', 42, undefined, 'x'.repeat(129)])
    assert.throws(
      () => validateAdmission({ ...body, joinCode }, settings.joinCode),
      (e: unknown) => e instanceof HttpError && e.status === 403,
    );
});

test('invalid admission never calls LiveKit', async () => {
  let called = false;
  const unreachable = {
    ...voice,
    createRoom: async () => {
      called = true;
      throw new Error('unexpected');
    },
  };
  await assert.rejects(
    issueVoiceToken({ ...body, joinCode: 'wrong' }, settings, unreachable),
  );
  assert.equal(called, false);
});

test('signed tokens expire in 60 seconds and permit only room-scoped microphone publishing and subscription', async () => {
  let cap = 0;
  const result = await issueVoiceToken(body, settings, {
    ...voice,
    createRoom: async (options) => {
      cap = options.maxParticipants;
      return {};
    },
  });
  const verifier = new TokenVerifier(settings.apiKey, settings.apiSecret);
  const claims = await verifier.verify(result.token);
  assert.equal(cap, 4);
  assert.equal(result.url, 'ws://127.0.0.1:7880');
  assert.equal(claims.name, 'Peach ♡');
  assert.match(claims.sub!, /^[a-f\d-]{36}$/);
  assert.ok(claims.exp! - Date.now() / 1000 <= TOKEN_TTL_SECONDS);
  assert.ok(claims.exp! - Date.now() / 1000 > TOKEN_TTL_SECONDS - 3);
  const payload = JSON.parse(
    Buffer.from(result.token.split('.')[1], 'base64url').toString(),
  );
  assert.deepEqual(payload.video, {
    roomJoin: true,
    room: 'pink-party',
    canSubscribe: true,
    canPublish: true,
    canPublishSources: ['microphone'],
    canPublishData: false,
    canUpdateOwnMetadata: false,
  });
  await assert.rejects(
    new TokenVerifier(settings.apiKey, 'wrong-secret').verify(result.token),
  );
});

test('capacity rejection and voice outage return actionable errors', async () => {
  await assert.rejects(
    issueVoiceToken(body, settings, {
      ...voice,
      listParticipants: async () => Array(4).fill({}),
    }),
    (e: unknown) => e instanceof HttpError && e.status === 409,
  );
  await assert.rejects(
    issueVoiceToken(body, settings, {
      ...voice,
      createRoom: async () => {
        throw new Error('ECONNREFUSED');
      },
    }),
    (e: unknown) => e instanceof HttpError && e.status === 503,
  );
});

test('configuration fails early for missing or example secrets', () => {
  assert.throws(() => loadSettings({}));
  assert.throws(() =>
    loadSettings({
      JOIN_CODE: 'replace-with-a-long-random-code',
      LIVEKIT_API_KEY: 'replace-with-random-key',
      LIVEKIT_API_SECRET: 'replace-with-at-least-32-random-characters',
    }),
  );
  assert.deepEqual(
    loadSettings({
      JOIN_CODE: settings.joinCode,
      LIVEKIT_API_KEY: settings.apiKey,
      LIVEKIT_API_SECRET: settings.apiSecret,
    }),
    settings,
  );
});

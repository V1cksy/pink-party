import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readSession, validateSession } from '../server/session.ts';
import { microphoneError } from '../src/voice.ts';

test('checked-in session is synthetic and has an explicit valid timezone and timestamp', async () => {
  const session = await readSession();
  assert.equal(session.synthetic, true);
  assert.equal(session.game, 'Stardew Valley');
  assert.equal(session.timeZone, 'Europe/Madrid');
  for (const invalid of [
    null,
    {},
    { ...session, game: '' },
    { ...session, synthetic: false },
    { ...session, timeZone: 'Moon/Crater' },
    { ...session, startsAt: '2026-11-07T20:00:00' },
    { ...session, startsAt: 'not a dateZ' },
  ])
    assert.throws(() => validateSession(invalid));
});

test('microphone failures explain specific recovery actions', () => {
  for (const [name, phrase] of [
    ['NotAllowedError', 'site settings'],
    ['NotFoundError', 'Connect an audio input'],
    ['NotReadableError', 'Close other apps'],
    ['UnknownError', 'audio input device'],
  ]) {
    const error = new Error('synthetic');
    error.name = name;
    assert.ok(microphoneError(error).includes(phrase));
  }
});

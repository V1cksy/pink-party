import { test, expect } from '@playwright/test';
import { writeFile } from 'node:fs/promises';
import { RoomServiceClient, AccessToken } from 'livekit-server-sdk';
import {
  instrument,
  joinRoom,
  receivedAudio,
  expectReleased,
} from './helpers.ts';
import { measureResources } from '../../scripts/measure.ts';

const admin = () =>
  new RoomServiceClient(
    'http://127.0.0.1:7880',
    process.env.LIVEKIT_API_KEY!,
    process.env.LIVEKIT_API_SECRET!,
    { requestTimeout: 3 },
  );

test('real voice: two-way audio, four peers, authoritative cap, mute, leave and rejoin', async ({
  browser,
  request,
}) => {
  test.setTimeout(150_000);
  const health = await request.get('/api/health');
  expect(health.ok()).toBe(true);
  const initialTokens: { token: string; url: string }[] = [];
  for (let i = 0; i < 5; i++) {
    const response = await request.post('/api/voice-token', {
      headers: { Origin: 'http://localhost:3000' },
      data: { displayName: `Peach ${i + 1}`, joinCode: process.env.JOIN_CODE },
    });
    expect(response.ok()).toBe(true);
    initialTokens.push(await response.json());
  }
  const contexts = await Promise.all(
    Array.from({ length: 5 }, () => browser.newContext()),
  );
  try {
    const pages = await Promise.all(
      contexts.map((context) => context.newPage()),
    );
    await Promise.all(pages.map(instrument));
    for (let i = 0; i < pages.length; i++)
      await pages[i].route('**/api/voice-token', (route) =>
        route.fulfill({ json: initialTokens[i] }),
      );
    await joinRoom(pages[0], 'Peach 1');
    await joinRoom(pages[1], 'Peach 2');
    for (const page of pages.slice(0, 2)) {
      await expect(page.locator('#participant-count')).toHaveText('2 / 4');
      await expect
        .poll(
          async () =>
            (await receivedAudio(page)).filter(
              (stat) =>
                stat.bytes > 1000 && stat.samples > 1000 && stat.energy > 0,
            ).length,
        )
        .toBe(1);
    }
    const two = await measureResources(
      '2 synthetic Chromium clients publishing and receiving audio',
      10,
    );
    const before = await Promise.all(pages.slice(0, 2).map(receivedAudio));
    await pages[0]
      .getByRole('button', { name: 'Mute microphone', exact: true })
      .click();
    await expect(
      pages[0].getByRole('button', { name: 'Unmute microphone', exact: true }),
    ).toHaveAttribute('aria-pressed', 'true');
    await expect(
      pages[1].locator('#participants li').filter({ hasText: 'Peach 1' }),
    ).toContainText('Muted');
    await pages[0]
      .getByRole('button', { name: 'Unmute microphone', exact: true })
      .click();
    await expect(
      pages[1].locator('#participants li').filter({ hasText: 'Peach 1' }),
    ).not.toContainText('Muted');
    for (let i = 0; i < 2; i++)
      await expect
        .poll(async () => (await receivedAudio(pages[i]))[0]?.energy ?? 0)
        .toBeGreaterThan(before[i][0].energy);
    await joinRoom(pages[2], 'Peach 3');
    await joinRoom(pages[3], 'Peach 4');
    for (const page of pages.slice(0, 4)) {
      await expect(page.locator('#participant-count')).toHaveText('4 / 4');
      await expect
        .poll(
          async () =>
            (await receivedAudio(page)).filter(
              (stat) =>
                stat.bytes > 1000 && stat.samples > 1000 && stat.energy > 0,
            ).length,
        )
        .toBe(3);
    }
    const four = await measureResources(
      '4 synthetic Chromium clients, each receiving 3 audio streams',
      10,
    );
    const media = await Promise.all(pages.slice(0, 4).map(receivedAudio));
    await writeFile(
      '.local/media-validation.json',
      JSON.stringify({ two, four, receivedAudioAtFourClients: media }, null, 2),
    );
    await pages[0].screenshot({
      path: '.local/four-clients.png',
      fullPage: true,
    });
    const full = await request.post('/api/voice-token', {
      headers: { Origin: 'http://localhost:3000' },
      data: { displayName: 'Extra', joinCode: process.env.JOIN_CODE },
    });
    expect(full.status()).toBe(409);
    const fifthClaims = JSON.parse(
      Buffer.from(initialTokens[4].token.split('.')[1], 'base64url').toString(),
    );
    expect(
      fifthClaims.exp - Date.now() / 1000,
      'Capacity test must use an unexpired token',
    ).toBeGreaterThan(5);
    const fifth = pages[4];
    await fifth.goto('/');
    await fifth.getByLabel('Display name', { exact: true }).fill('Peach 5');
    await fifth
      .getByLabel('Local join code', { exact: true })
      .fill(process.env.JOIN_CODE!);
    await fifth
      .getByRole('button', { name: 'Join voice room', exact: true })
      .click();
    await expect(fifth.locator('#connection-state')).toHaveText('Error');
    await expectReleased(fifth);
    expect((await admin().listParticipants('pink-party')).length).toBe(4);
    await pages[0]
      .getByRole('button', { name: 'Leave room', exact: true })
      .click();
    await expectReleased(pages[0]);
    await expect(pages[1].locator('#participant-count')).toHaveText('3 / 4');
    await expect(pages[1].locator('audio')).toHaveCount(2);
    await pages[0].unroute('**/api/voice-token');
    await joinRoom(pages[0], 'Peach returns');
    await expect(pages[1].locator('#participant-count')).toHaveText('4 / 4');
    await expect(pages[1].locator('#participants')).toContainText(
      'Peach returns',
    );
    await expect(pages[1].locator('#participants')).not.toContainText(
      'Peach 1',
    );
    // A server-initiated disconnect must also clear tracks and the participant UI.
    const removed = (await admin().listParticipants('pink-party')).find(
      (person) => person.name === 'Peach returns',
    )!;
    await admin().removeParticipant('pink-party', removed.identity);
    await expect(pages[0].locator('#connection-state')).toHaveText(
      'Disconnected',
    );
    await expectReleased(pages[0]);
    for (const page of pages.slice(1, 4))
      await page
        .getByRole('button', { name: 'Leave room', exact: true })
        .click();
    for (const page of pages.slice(0, 4)) await expectReleased(page);
    await expect
      .poll(async () => (await admin().listParticipants('pink-party')).length)
      .toBe(0);
  } finally {
    await Promise.all(contexts.map((context) => context.close()));
  }
});

test('LiveKit rejects an already expired room token', async ({ page }) => {
  await instrument(page);
  const token = new AccessToken(
    process.env.LIVEKIT_API_KEY!,
    process.env.LIVEKIT_API_SECRET!,
    { identity: 'synthetic-expired', ttl: -60 },
  );
  token.addGrant({ roomJoin: true, room: 'pink-party' });
  const jwt = await token.toJwt();
  await page.route('**/api/voice-token', (route) =>
    route.fulfill({ json: { token: jwt, url: 'ws://127.0.0.1:7880' } }),
  );
  await page.goto('/');
  await page.getByLabel('Display name', { exact: true }).fill('Expired');
  await page.getByLabel('Local join code', { exact: true }).fill('synthetic');
  await page
    .getByRole('button', { name: 'Join voice room', exact: true })
    .click();
  await expect(page.locator('#connection-state')).toHaveText('Error');
  await expectReleased(page);
});

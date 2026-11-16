import { test, expect } from '@playwright/test';
import { mkdir, writeFile } from 'node:fs/promises';
import { get } from 'node:https';
import { RoomServiceClient } from 'livekit-server-sdk';
import { loadSettings, LIVEKIT_HTTP } from '../../server/config.ts';
import { verifyPrivateNetwork } from '../../scripts/tailscale.ts';
import { measureResources, tailscaleProcesses } from '../../scripts/measure.ts';
import {
  instrument,
  receivedAudio,
  expectReleased,
} from '../browser/helpers.ts';

test('real Serve: trusted TLS, replaced identity, WSS 101 and private UDP media (synthetic microphones, same Mac)', async ({
  browser,
  request,
}) => {
  const settings = loadSettings(process.env);
  const access = settings.privateAccess;
  if (!access) throw new Error('Private settings required.');
  await verifyPrivateNetwork(access);
  const voice = new RoomServiceClient(
    LIVEKIT_HTTP,
    settings.apiKey,
    settings.apiSecret,
    { requestTimeout: 3 },
  );
  const rooms = await voice.listRooms(['pink-party']);
  expect(rooms[0]?.numParticipants ?? 0, 'Use an empty test room').toBe(0);

  // No test CA, certificate exception, fake proxy, or injected login is used.
  await new Promise<void>((resolve, reject) => {
    const req = get(access.origin + '/api/access', (res) => {
      const accepted = res.statusCode === 200;
      res.resume();
      res.on('end', () =>
        accepted
          ? resolve()
          : reject(
              new Error(
                'Serve identity was not accepted; check the allowlist and client path.',
              ),
            ),
      );
    });
    req.setTimeout(8000, () => req.destroy(new Error('HTTPS timeout')));
    req.on('error', () =>
      reject(new Error('Trusted HTTPS/identity check failed.')),
    );
  });
  const granted = await request.get('/api/access');
  expect(await granted.json()).toEqual({ mode: 'private' });
  // A forged denied login must not replace the real, invited owner identity.
  expect(
    (
      await request.get('/api/access', {
        headers: { 'Tailscale-User-Login': 'stranger@example.com' },
      })
    ).status(),
  ).toBe(200);
  expect(
    (
      await request.get('/api/access', {
        headers: { Origin: 'https://evil.example' },
      })
    ).status(),
  ).toBe(403);
  const wrongHostStatus = await new Promise<number>((resolve, reject) => {
    // Keep TLS SNI correct so this probes HTTP Host, not a TLS name mismatch.
    const req = get(
      access.origin + '/api/access',
      {
        servername: new URL(access.origin).hostname,
        headers: { Host: 'localhost:3000' },
      },
      (res) => {
        res.resume();
        res.on('end', () => resolve(res.statusCode ?? 0));
      },
    );
    req.setTimeout(8000, () => req.destroy(new Error('HTTPS timeout')));
    req.on('error', () =>
      reject(new Error('HTTP Host probe transport failed.')),
    );
  });
  expect(wrongHostStatus).toBeGreaterThanOrEqual(400);
  expect(
    (
      await request.post('/api/voice-token', {
        data: { displayName: 'Synthetic origin probe' },
      })
    ).status(),
  ).toBe(403);
  expect(
    (
      await request.get('/livekit/twirp/livekit.RoomService/ListRooms')
    ).status(),
  ).toBe(404);

  const contexts = await Promise.all([
    browser.newContext(),
    browser.newContext(),
  ]);
  const upgrades: number[] = [];
  try {
    const pages = await Promise.all(
      contexts.map((context) => context.newPage()),
    );
    for (const page of pages) {
      await instrument(page);
      const cdp = await page.context().newCDPSession(page);
      await cdp.send('Network.enable');
      cdp.on('Network.webSocketHandshakeResponseReceived', (event) => {
        upgrades.push(event.response.status);
      });
      const response = await page.goto(access.origin);
      expect(response?.status()).toBe(200);
      expect(response?.headers()['content-security-policy']).toContain(
        access.origin.replace('https:', 'wss:') + '/livekit',
      );
      expect(await page.evaluate(() => window.isSecureContext)).toBe(true);
      await expect(page.locator('#access-badge')).toHaveText('Private hangout');
      await expect(
        page.getByLabel('Local join code', { exact: true }),
      ).toBeHidden();
    }
    for (let i = 0; i < pages.length; i++) {
      await pages[i]
        .getByLabel('What should we call you?')
        .fill(`Tailnet test ${i + 1}`);
      await pages[i]
        .getByRole('button', { name: 'Join voice room', exact: true })
        .click();
      await expect(pages[i].locator('#connection-state')).toHaveText(
        'Connected',
      );
    }
    for (const page of pages) {
      await expect(page.locator('#participant-count')).toHaveText('2 / 4');
      await expect
        .poll(
          async () =>
            (await receivedAudio(page)).filter(
              (s) => s.bytes > 1000 && s.samples > 1000 && s.energy > 0,
            ).length,
        )
        .toBe(1);
    }
    await expect
      .poll(() => upgrades.filter((status) => status === 101).length)
      .toBe(2);
    const candidates = await Promise.all(
      pages.map((page) =>
        page.evaluate(async () => {
          const reports = await Promise.all(
            window.testPeers.map((peer) => peer.getStats()),
          );
          return reports.flatMap((report) =>
            [...report.values()]
              .filter(
                (stat) =>
                  stat.type === 'transport' && stat.selectedCandidatePairId,
              )
              .map((stat) => {
                const pair = report.get(stat.selectedCandidatePairId);
                const remote = report.get(pair.remoteCandidateId);
                return {
                  state: pair.state,
                  remoteAddress: remote.address ?? remote.ip,
                  remotePort: remote.port,
                  protocol: remote.protocol,
                  candidateType: remote.candidateType,
                };
              }),
          );
        }),
      ),
    );
    for (const client of candidates) {
      expect(client.length).toBeGreaterThan(0);
      for (const pair of client) {
        expect(pair.state).toBe('succeeded');
        // Keep private addresses out of assertion failure output.
        expect(pair.remoteAddress === access.tailscaleIp).toBe(true);
        expect(pair.remotePort).toBe(7882);
        expect(pair.protocol).toBe('udp');
      }
    }
    await pages[0]
      .getByRole('button', { name: 'Mute microphone', exact: true })
      .click();
    await expect(
      pages[1]
        .locator('#participants li')
        .filter({ hasText: 'Tailnet test 1' }),
    ).toContainText('Muted');
    await pages[0]
      .getByRole('button', { name: 'Unmute microphone', exact: true })
      .click();
    await expect(
      pages[1]
        .locator('#participants li')
        .filter({ hasText: 'Tailnet test 1' }),
    ).not.toContainText('Muted');
    const before = await receivedAudio(pages[1]);
    await expect
      .poll(async () => (await receivedAudio(pages[1]))[0]?.energy ?? 0)
      .toBeGreaterThan(before[0].energy);
    const media = await Promise.all(pages.map(receivedAudio));
    const resources = await measureResources(
      'Real Serve, 2 synthetic Chromium clients on one Mac; no remote peer or human speech',
      10,
      undefined,
      tailscaleProcesses(),
    );
    await pages[0].screenshot({
      path: '.local/real-serve-interface.png',
      fullPage: true,
    });
    for (const page of pages) {
      await page
        .getByRole('button', { name: 'Leave room', exact: true })
        .click();
      await expectReleased(page);
    }
    await mkdir('.local', { recursive: true, mode: 0o700 });
    await writeFile(
      '.local/real-serve-validation.json',
      JSON.stringify(
        {
          capturedAt: new Date().toISOString(),
          realServe: true,
          certificateExceptions: false,
          syntheticMicrophones: true,
          physicalDevices: 1,
          separateHomeCall: false,
          upgrades,
          candidates,
          receivedAudio: media,
          resources,
          notEstablishedByThisSuite: [
            'Uninvited/tagged peer and forged allowed login from that peer',
            'Physical microphone/playback quality and separate-home human call',
            'Client network interruption and Tailscale direct/relay observation',
          ],
        },
        null,
        2,
      ) + '\n',
      { mode: 0o600 },
    );
  } finally {
    await Promise.all(contexts.map((context) => context.close()));
  }
});

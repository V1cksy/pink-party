import { measureResources } from '../../scripts/measure.ts';
import type { WebSocketRoute } from '@playwright/test';
import { test, expect } from '@playwright/test';
import {
  instrument,
  receivedAudio,
  expectReleased,
} from '../browser/helpers.ts';
import { readFile, writeFile } from 'node:fs/promises';
import { get } from 'node:https';

test('synthetic TLS proxy: verified fixture certificate, protected WSS, two real media clients, mute and cleanup', async ({
  browser,
}) => {
  const ca = await readFile('.local/test-cert.pem');
  await new Promise<void>((resolve, reject) => {
    get('https://localhost:3443/api/health', { ca }, (response) => {
      expect(response.statusCode).toBe(200);
      response.resume();
      response.on('end', resolve);
    }).on('error', reject);
  });
  const contexts = await Promise.all(
    ['peach@example.com', 'berry@example.com'].map((login) =>
      browser.newContext({
        ignoreHTTPSErrors: true,
        extraHTTPHeaders: { 'X-Test-Login': login },
      }),
    ),
  );
  try {
    const pages = await Promise.all(
      contexts.map((context) => context.newPage()),
    );
    const upgrades: string[] = [];
    let signal: WebSocketRoute | undefined;
    await pages[0].routeWebSocket(
      'wss://localhost:3443/livekit/**',
      (route) => {
        route.connectToServer();
        signal ??= route;
      },
    );
    for (let i = 0; i < pages.length; i++) {
      const page = pages[i];
      await instrument(page);
      page.on('websocket', (socket) =>
        upgrades.push(socket.url().split('?')[0]),
      );
      await page.goto('https://localhost:3443/');
      expect(await page.evaluate(() => window.isSecureContext)).toBe(true);
      await expect(page.locator('#access-badge')).toHaveText('Private room');
      await expect(
        page.getByLabel('Local join code', { exact: true }),
      ).toBeHidden();
      const inputWidth = await page
        .locator('#display-name')
        .evaluate((input) => input.getBoundingClientRect().width);
      const rowWidth = await page
        .locator('.form-fields')
        .evaluate((row) => row.getBoundingClientRect().width);
      expect(inputWidth).toBeCloseTo(rowWidth, 0);
      await page
        .getByLabel('Display name', { exact: true })
        .fill(`Remote fixture ${i + 1}`);
      await page
        .getByRole('button', { name: 'Join voice room', exact: true })
        .click();
      await expect(page.locator('#connection-state')).toHaveText('Connected');
    }
    for (const page of pages) {
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
    expect(upgrades).toEqual([
      'wss://localhost:3443/livekit/rtc/v1',
      'wss://localhost:3443/livekit/rtc/v1',
    ]);
    await pages[0]
      .getByRole('button', { name: 'Mute microphone', exact: true })
      .click();
    await expect(
      pages[1]
        .locator('#participants li')
        .filter({ hasText: 'Remote fixture 1' }),
    ).toContainText('Muted');
    await pages[0]
      .getByRole('button', { name: 'Unmute microphone', exact: true })
      .click();
    await expect(
      pages[1]
        .locator('#participants li')
        .filter({ hasText: 'Remote fixture 1' }),
    ).not.toContainText('Muted');
    const resources = await measureResources(
      '2 synthetic clients through synthetic HTTPS/identity proxy, real loopback media',
      10,
      [
        { name: 'fixture proxy and application', port: 3443 },
        { name: 'LiveKit', port: 7880 },
      ],
    );
    await pages[0].evaluate(() => {
      document.getElementById('connection-state')!.dataset.testReconnect = '';
      new MutationObserver(() => {
        if (
          document.getElementById('connection-state')!.dataset.state ===
          'reconnecting'
        )
          document.getElementById('connection-state')!.dataset.testReconnect =
            'seen';
      }).observe(document.getElementById('connection-state')!, {
        attributes: true,
        attributeFilter: ['data-state'],
      });
    });
    if (!signal) throw new Error('No secure signaling intercepted');
    signal.close({ code: 1011, reason: 'Synthetic signaling interruption' });
    await expect(pages[0].locator('#connection-state')).toHaveAttribute(
      'data-test-reconnect',
      'seen',
    );
    await expect(pages[0].locator('#connection-state')).toHaveText(
      'Connected',
      { timeout: 30_000 },
    );
    await pages[0].screenshot({
      path: '.local/private-interface.png',
      fullPage: true,
    });
    const media = await Promise.all(pages.map(receivedAudio));
    await pages[0]
      .getByRole('button', { name: 'Leave room', exact: true })
      .click();
    await expectReleased(pages[0]);
    await expect(pages[1].locator('#participant-count')).toHaveText('1 / 4');
    await pages[1]
      .getByRole('button', { name: 'Leave room', exact: true })
      .click();
    await expectReleased(pages[1]);
    await writeFile(
      '.local/private-proxy-validation.json',
      JSON.stringify(
        {
          syntheticIdentity: true,
          syntheticTls: true,
          transport: 'real native LiveKit, loopback media',
          upgrades,
          receivedAudio: media,
          resources,
        },
        null,
        2,
      ),
    );
  } finally {
    await Promise.all(contexts.map((context) => context.close()));
  }
});

test('synthetic proxy rejects denied identity and overwrites forged browser identity', async ({
  browser,
}) => {
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    extraHTTPHeaders: {
      'X-Test-Login': 'stranger@example.com',
      'Tailscale-User-Login': 'peach@example.com',
    },
  });
  try {
    const page = await context.newPage();
    const response = await page.goto('https://localhost:3443/');
    expect(response?.status()).toBe(403);
    expect(await page.locator('body').textContent()).toContain('not invited');
    expect(
      await page.evaluate(() => document.querySelectorAll('audio').length),
    ).toBe(0);
  } finally {
    await context.close();
  }
});

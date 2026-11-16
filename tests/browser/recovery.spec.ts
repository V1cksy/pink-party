import { test, expect } from '@playwright/test';
import type { WebSocketRoute } from '@playwright/test';
import { RoomServiceClient } from 'livekit-server-sdk';
import { instrument, joinRoom, expectReleased } from './helpers.ts';

async function fillJoin(page: import('@playwright/test').Page) {
  await page.goto('/');
  await page
    .getByLabel('Display name', { exact: true })
    .fill('Synthetic guest');
  await page
    .getByLabel('Local join code', { exact: true })
    .fill(process.env.JOIN_CODE!);
}

for (const [name, message] of [
  ['NotAllowedError', 'permission was denied'],
  ['NotFoundError', 'No microphone found'],
  ['NotReadableError', 'microphone is unavailable'],
]) {
  test(`${name}: explain recovery and leave no media or participants`, async ({
    page,
  }) => {
    await instrument(page);
    await page.addInitScript((errorName) => {
      navigator.mediaDevices.getUserMedia = async () => {
        throw new DOMException('Synthetic device failure', errorName);
      };
    }, name);
    await fillJoin(page);
    await page
      .getByRole('button', { name: 'Join voice room', exact: true })
      .click();
    await expect(page.locator('#connection-state')).toHaveText('Error');
    await expect(page.locator('#room-message')).toContainText(message);
    await expectReleased(page);
    await expect(
      page.getByRole('button', { name: 'Join voice room', exact: true }),
    ).toBeEnabled();
  });
}

test('wrong admission code rejects before opening a microphone', async ({
  page,
}) => {
  await instrument(page);
  await fillJoin(page);
  await page.getByLabel('Local join code', { exact: true }).fill('wrong-code');
  await page
    .getByRole('button', { name: 'Join voice room', exact: true })
    .click();
  await expect(page.locator('#room-message')).toContainText(
    'join code did not match',
  );
  expect(await page.evaluate(() => window.testTracks.length)).toBe(0);
});

test('cancel during microphone permission, duplicate join, and late capture all clean up', async ({
  page,
}) => {
  await instrument(page);
  await page.addInitScript(() => {
    const capture = navigator.mediaDevices.getUserMedia;
    navigator.mediaDevices.getUserMedia = async (constraints) => {
      await new Promise((resolve) => setTimeout(resolve, 2000));
      return capture(constraints);
    };
  });
  let requests = 0;
  page.on('request', (request) => {
    if (request.url().endsWith('/api/voice-token')) requests++;
  });
  await fillJoin(page);
  await page.locator('#join-form').evaluate((form) => {
    form.dispatchEvent(
      new Event('submit', { bubbles: true, cancelable: true }),
    );
    form.dispatchEvent(
      new Event('submit', { bubbles: true, cancelable: true }),
    );
  });
  await expect(page.locator('#room-message')).toContainText(
    'Allow your microphone',
  );
  await page.getByRole('button', { name: 'Cancel join', exact: true }).click();
  await expect(page.locator('#connection-state')).toHaveText('Disconnected');
  await expect
    .poll(() => page.evaluate(() => window.testTracks.length))
    .toBe(1);
  await expectReleased(page);
  expect(requests).toBe(1);
});

test('unreachable real voice endpoint releases a captured microphone', async ({
  page,
}) => {
  await instrument(page);
  await page.route('**/api/voice-token', async (route) => {
    const response = await route.fetch();
    const result = await response.json();
    // Keep a real signed token and replace only the network destination.
    await route.fulfill({ json: { ...result, url: 'ws://127.0.0.1:7999' } });
  });
  await fillJoin(page);
  await page
    .getByRole('button', { name: 'Join voice room', exact: true })
    .click();
  await expect(page.locator('#connection-state')).toHaveText('Error');
  await expect(page.locator('#room-message')).toContainText(
    'Could not connect',
  );
  await expectReleased(page);
});

test('blocked playback has a working Enable sound recovery action', async ({
  browser,
}) => {
  const context = await browser.newContext();
  const sender = await context.newPage();
  const receiver = await context.newPage();
  try {
    await Promise.all([sender, receiver].map(instrument));
    await receiver.addInitScript(() => {
      const play = HTMLMediaElement.prototype.play;
      let blocked = true;
      HTMLMediaElement.prototype.play = function () {
        if (blocked)
          return Promise.reject(
            new DOMException('Synthetic autoplay block', 'NotAllowedError'),
          );
        return play.call(this);
      };
      document.addEventListener(
        'click',
        (event) => {
          if ((event.target as HTMLElement).id === 'playback-button')
            blocked = false;
        },
        { capture: true },
      );
    });
    await joinRoom(sender, 'Sender');
    await joinRoom(receiver, 'Receiver');
    await expect(
      receiver.getByRole('button', { name: 'Enable sound', exact: true }),
    ).toBeVisible();
    await receiver
      .getByRole('button', { name: 'Enable sound', exact: true })
      .click();
    await expect(
      receiver.getByRole('button', { name: 'Enable sound', exact: true }),
    ).toBeHidden();
    expect(
      await receiver
        .locator('audio')
        .evaluateAll((elements) =>
          elements.every((element) => !(element as HTMLAudioElement).paused),
        ),
    ).toBe(true);
  } finally {
    for (const page of [sender, receiver]) {
      if (await page.locator('#leave-button:visible').count())
        await page.locator('#leave-button').click();
    }
    await context.close();
  }
});

test('real signaling transport loss reconnects, then leaves cleanly', async ({
  page,
}) => {
  await instrument(page);
  let firstSignal: WebSocketRoute | undefined;
  await page.routeWebSocket('ws://127.0.0.1:7880/**', (route) => {
    route.connectToServer();
    firstSignal ??= route;
  });
  await joinRoom(page, 'Reconnecting guest');
  await page.evaluate(() => {
    (window as unknown as { connectionHistory: string[] }).connectionHistory =
      [];
    new MutationObserver(() => {
      (
        window as unknown as { connectionHistory: string[] }
      ).connectionHistory.push(
        document.getElementById('connection-state')!.dataset.state!,
      );
    }).observe(document.getElementById('connection-state')!, {
      attributes: true,
    });
  });
  if (!firstSignal) throw new Error('Signaling socket was not intercepted');
  firstSignal.close({
    code: 1011,
    reason: 'Synthetic local signaling interruption',
  });
  await expect
    .poll(() =>
      page.evaluate(() =>
        (
          window as unknown as { connectionHistory: string[] }
        ).connectionHistory.includes('reconnecting'),
      ),
    )
    .toBe(true);
  await expect(page.locator('#connection-state')).toHaveText('Connected', {
    timeout: 30_000,
  });
  await expect(page.locator('#participant-count')).toHaveText('1 / 4');
  await page.getByRole('button', { name: 'Leave room', exact: true }).click();
  await expectReleased(page);
});

test('responsive interface, keyboard labels and synthetic session are visible', async ({
  page,
}) => {
  await page.goto('/');
  await expect(
    page.getByRole('heading', { name: 'Stardew Valley', exact: true }),
  ).toBeVisible();
  await expect(page.locator('#session-time')).toContainText('Europe/Madrid');
  await expect(page.locator('#session-time')).toContainText('GMT+1');
  await page.keyboard.press('Tab');
  await expect(
    page.getByRole('link', { name: 'Skip to voice room', exact: true }),
  ).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.locator('#voice-room')).toBeFocused();
  await page.getByRole('heading', { name: 'Anyone up for a game?' }).click();
  await page.screenshot({ path: '.local/desktop.png', fullPage: true });
  for (const width of [320, 390, 680, 900, 1440]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(
      page.getByLabel('Display name', { exact: true }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= innerWidth,
      ),
      `No page overflow at ${width}px`,
    ).toBe(true);
    const button = await page.locator('#join-button').boundingBox();
    expect(button!.height).toBeGreaterThanOrEqual(44);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: '.local/mobile.png', fullPage: true });
});

test.afterEach(async ({ context }) => {
  for (const page of context.pages()) {
    if (await page.locator('#leave-button:visible').count())
      await page.locator('#leave-button').click();
  }
  const admin = new RoomServiceClient(
    'http://127.0.0.1:7880',
    process.env.LIVEKIT_API_KEY!,
    process.env.LIVEKIT_API_SECRET!,
    { requestTimeout: 3 },
  );
  await expect
    .poll(async () => (await admin.listParticipants('pink-party')).length)
    .toBe(0);
});

test('leave during delayed unmute stops a late microphone capture', async ({
  page,
}) => {
  await instrument(page);
  await page.addInitScript(() => {
    const capture = navigator.mediaDevices.getUserMedia;
    let calls = 0;
    navigator.mediaDevices.getUserMedia = async (constraints) => {
      calls++;
      if (calls > 1) await new Promise((resolve) => setTimeout(resolve, 1500));
      return capture(constraints);
    };
  });
  await joinRoom(page, 'Late unmute');
  await page
    .getByRole('button', { name: 'Mute microphone', exact: true })
    .click();
  await page
    .getByRole('button', { name: 'Unmute microphone', exact: true })
    .click();
  await page.getByRole('button', { name: 'Leave room', exact: true }).click();
  await expect
    .poll(() => page.evaluate(() => window.testTracks.length))
    .toBe(2);
  await expectReleased(page);
});

test('device-ended SDK recovery cannot reopen the microphone after cleanup', async ({
  page,
}) => {
  await instrument(page);
  await page.addInitScript(() => {
    const query = navigator.permissions.query.bind(navigator.permissions);
    navigator.permissions.query = async (descriptor) => {
      // Let application disconnect finish before the SDK's device recovery resumes.
      if (descriptor.name === 'microphone')
        await new Promise((resolve) => setTimeout(resolve, 500));
      return query(descriptor);
    };
    const capture = navigator.mediaDevices.getUserMedia;
    let calls = 0;
    navigator.mediaDevices.getUserMedia = async (constraints) => {
      calls++;
      if (calls > 1) await new Promise((resolve) => setTimeout(resolve, 1000));
      return capture(constraints);
    };
  });
  await joinRoom(page, 'Device-ended guest');
  await page.evaluate(() => {
    const track = window.testTracks.find(
      (track) => track.readyState === 'live',
    )!;
    track.stop();
    track.dispatchEvent(new Event('ended'));
  });
  await expect(page.locator('#connection-state')).toHaveText('Error');
  await expect(page.locator('#room-message')).toContainText(
    'Microphone disconnected',
  );
  await expect
    .poll(() => page.evaluate(() => window.testTracks.length))
    .toBe(2);
  await expectReleased(page);
});

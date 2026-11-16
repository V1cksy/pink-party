import { expect } from '@playwright/test';
import type { Page } from '@playwright/test';

declare global {
  interface Window {
    testPeers: RTCPeerConnection[];
    testTracks: MediaStreamTrack[];
  }
}
export async function instrument(page: Page) {
  await page.addInitScript(() => {
    window.testPeers = [];
    window.testTracks = [];
    const Original = window.RTCPeerConnection;
    window.RTCPeerConnection = class extends Original {
      constructor(config?: RTCConfiguration) {
        super(config);
        window.testPeers.push(this);
      }
    };
    const originalCapture = navigator.mediaDevices.getUserMedia.bind(
      navigator.mediaDevices,
    );
    navigator.mediaDevices.getUserMedia = async (constraints) => {
      const stream = await originalCapture(constraints);
      window.testTracks.push(...stream.getTracks());
      return stream;
    };
  });
}
export async function joinRoom(page: Page, name: string) {
  await page.goto('/');
  await page.getByLabel('Display name', { exact: true }).fill(name);
  await page
    .getByLabel('Local join code', { exact: true })
    .fill(process.env.JOIN_CODE!);
  await page
    .getByRole('button', { name: 'Join voice room', exact: true })
    .click();
  await expect(
    page.locator('#connection-state'),
    (await page.locator('#room-message').textContent()) ?? '',
  ).toHaveText('Connected');
}
export async function receivedAudio(page: Page) {
  return page.evaluate(async () => {
    const stats = (
      await Promise.all(window.testPeers.map((peer) => peer.getStats()))
    ).flatMap((report) => [...report.values()]);
    return stats
      .filter((stat) => stat.type === 'inbound-rtp' && stat.kind === 'audio')
      .map((stat) => ({
        bytes: stat.bytesReceived ?? 0,
        samples: stat.totalSamplesReceived ?? 0,
        energy: stat.totalAudioEnergy ?? 0,
      }));
  });
}
export async function expectReleased(page: Page) {
  await expect
    .poll(() =>
      page.evaluate(() =>
        window.testTracks.every((track) => track.readyState === 'ended'),
      ),
    )
    .toBe(true);
  await expect(page.locator('audio')).toHaveCount(0);
  await expect(page.locator('#participants li')).toHaveCount(0);
}

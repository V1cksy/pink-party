import { defineConfig } from '@playwright/test';
import { resolve } from 'node:path';
export default defineConfig({
  testDir: './tests/private-browser',
  testMatch: '*.spec.ts',
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: 'list',
  webServer: {
    command: 'node --env-file=.env tests/private-browser/fixture.ts',
    url: 'https://localhost:3443/api/health',
    ignoreHTTPSErrors: true,
    reuseExistingServer: false,
  },
  use: {
    baseURL: 'https://localhost:3443',
    browserName: 'chromium',
    ignoreHTTPSErrors: true,
    launchOptions: {
      args: [
        '--use-fake-device-for-media-stream',
        '--use-fake-ui-for-media-stream',
        `--use-file-for-fake-audio-capture=${resolve('.local/test-tone.wav')}`,
        '--autoplay-policy=no-user-gesture-required',
      ],
    },
    trace: 'off',
    screenshot: 'off',
  },
});

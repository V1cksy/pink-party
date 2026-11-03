import { defineConfig } from '@playwright/test';
import { resolve } from 'node:path';
import { loadEnvFile } from 'node:process';
loadEnvFile('.env');
export default defineConfig({
  testDir: './tests/browser',
  workers: 1,
  fullyParallel: false,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: 'list',
  use: {
    baseURL: 'http://localhost:3000',
    browserName: 'chromium',
    viewport: { width: 1440, height: 1100 },
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

import { defineConfig } from '@playwright/test';
import { loadEnvFile } from 'node:process';
import { resolve } from 'node:path';
import { loadSettings } from './server/config.ts';

loadEnvFile('.env.private');
const settings = loadSettings(process.env);
if (!settings.privateAccess) throw new Error('Private settings required.');

export default defineConfig({
  testDir: './tests/tailnet-browser',
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: 'list',
  use: {
    baseURL: settings.privateAccess.origin,
    browserName: 'chromium',
    ignoreHTTPSErrors: false,
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

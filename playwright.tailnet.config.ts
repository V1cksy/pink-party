import { defineConfig } from '@playwright/test';
import { loadEnvFile } from 'node:process';
import { resolve } from 'node:path';
import { loadSettings } from './server/config.ts';
import { readRemoteTarget } from './deploy/cloud/target.ts';

const remote = process.env.PINK_PARTY_CLOUD_TARGET;
if (!remote) loadEnvFile('.env.private');
const access = remote
  ? await readRemoteTarget(remote)
  : loadSettings(process.env).privateAccess;
if (!access) throw new Error('Private settings required.');

export default defineConfig({
  testDir: './tests/tailnet-browser',
  workers: 1,
  timeout: 90_000,
  expect: { timeout: 15_000 },
  reporter: 'list',
  use: {
    baseURL: access.origin,
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

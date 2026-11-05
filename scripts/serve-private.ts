import { spawn } from 'node:child_process';
import { mkdir, writeFile, chmod } from 'node:fs/promises';
import { loadSettings } from '../server/config.ts';
import {
  assertServePortFree,
  tailscale,
  tailscaleBinary,
  verifyPrivateNetwork,
} from './tailscale.ts';

try {
  const settings = loadSettings(process.env);
  if (!settings.privateAccess)
    throw new Error('Private configuration required.');
  await verifyPrivateNetwork(settings.privateAccess);
  const config = await tailscale(['serve', 'status', '--json']);
  assertServePortFree(JSON.parse(config));
  await mkdir('.local', { recursive: true, mode: 0o700 });
  await chmod('.local', 0o700);
  await writeFile(`.local/serve-before-${Date.now()}.json`, config, {
    flag: 'wx',
    mode: 0o600,
  });
  const child = spawn(
    await tailscaleBinary(),
    ['serve', '--https=443', 'http://127.0.0.1:3000'],
    { stdio: 'inherit' },
  );
  for (const signal of ['SIGINT', 'SIGTERM'] as const)
    process.on(signal, () => child.kill(signal));
  child.on('error', () => {
    console.error('Cannot start Tailscale Serve.');
    process.exitCode = 1;
  });
  child.on('exit', (code) => {
    process.exitCode = code ?? 0;
  });
} catch (error) {
  console.error(error instanceof Error ? error.message : 'Serve setup failed.');
  process.exitCode = 1;
}

import { readFile, mkdir, writeFile, chmod } from 'node:fs/promises';
import { parseEnv } from 'node:util';
import { loadSettings } from '../server/config.ts';
import { networkStatus } from './tailscale.ts';

try {
  const status = await networkStatus();
  const local = loadSettings(parseEnv(await readFile('.env', 'utf8')));
  await mkdir('.local', { recursive: true, mode: 0o700 });
  await chmod('.local', 0o700);
  try {
    await writeFile('.local/invited-logins.txt', `${status.login}\n`, {
      flag: 'wx',
      mode: 0o600,
    });
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'EEXIST') throw error;
  }
  const logins = (await readFile('.local/invited-logins.txt', 'utf8'))
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter((line) => line && !line.startsWith('#'));
  const env = {
    PINK_PARTY_MODE: 'private',
    PUBLIC_ORIGIN: status.origin,
    TAILSCALE_IP: status.ip,
    INVITED_LOGINS: logins.join(','),
    LIVEKIT_API_KEY: local.apiKey,
    LIVEKIT_API_SECRET: local.apiSecret,
  };
  loadSettings(env);
  await writeFile(
    '.env.private',
    Object.entries(env)
      .map(([key, value]) => `${key}=${JSON.stringify(value)}`)
      .join('\n') + '\n',
    { mode: 0o600 },
  );
  await chmod('.env.private', 0o600);
  await chmod('.local/invited-logins.txt', 0o600);
  console.log(
    'Wrote ignored .env.private. The initial allowlist contains only this device’s verified owner. Edit .local/invited-logins.txt, rerun this command, and restart private mode to apply changes.',
  );
} catch (error) {
  console.error(
    error instanceof Error ? error.message : 'Private setup failed.',
  );
  process.exitCode = 1;
}

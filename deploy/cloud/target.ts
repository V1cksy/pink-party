import { readFile } from 'node:fs/promises';
import { loadSettings } from '../../server/config.ts';

export async function readRemoteTarget(path: string) {
  const data = await readFile(path, 'utf8');
  if (data.length > 4096) throw new Error('Remote target is too large.');
  const target = JSON.parse(data);
  if (!target || Object.keys(target).sort().join(',') !== 'origin,tailscaleIp')
    throw new Error('Remote target requires only origin and tailscaleIp.');
  const settings = loadSettings({
    PINK_PARTY_MODE: 'private',
    PUBLIC_ORIGIN: target.origin,
    TAILSCALE_IP: target.tailscaleIp,
    INVITED_LOGINS: 'syntactic-validation@example.com',
    LIVEKIT_API_KEY: 'synthetic-validation-key',
    LIVEKIT_API_SECRET: 'synthetic-validation-secret-at-least-32',
  });
  return settings.privateAccess!;
}

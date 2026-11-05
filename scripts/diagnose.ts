import { loadSettings } from '../server/config.ts';
import { RoomServiceClient } from 'livekit-server-sdk';
import { LIVEKIT_HTTP } from '../server/config.ts';
import { tailscale, verifyPrivateNetwork } from './tailscale.ts';

const settings = loadSettings(process.env);
async function check(label: string, action: () => Promise<unknown>) {
  try {
    await action();
    console.log(`${label}: OK`);
  } catch {
    console.log(`${label}: FAILED (see docs/remote-access.md)`);
    process.exitCode = 1;
  }
}
await check('LiveKit authenticated control API (not media)', () =>
  new RoomServiceClient(LIVEKIT_HTTP, settings.apiKey, settings.apiSecret, {
    requestTimeout: 3,
  }).listRooms(),
);
if (settings.privateAccess) {
  const config = settings.privateAccess;
  await check('Tailscale device matches private configuration', () =>
    verifyPrivateNetwork(config),
  );
  await check('Serve configuration readable', () =>
    tailscale(['serve', 'status', '--json']),
  );
  const get = (path: string) =>
    fetch(config.origin + path, {
      signal: AbortSignal.timeout(8000),
      redirect: 'error',
    });
  await check(
    'HTTPS transport and certificate (a 403 still proves transport)',
    async () => {
      const response = await get('/api/access');
      await response.body?.cancel();
    },
  );
  await check('Verified identity accepted by application', async () => {
    const response = await get('/api/access');
    if (!response.ok || (await response.json()).mode !== 'private')
      throw new Error('Identity rejected');
  });
  await check('Application health through HTTPS', async () => {
    const response = await get('/api/health');
    if (!response.ok) throw new Error('App/voice failed');
    await response.body?.cancel();
  });
} else {
  await check('Local web/API health', async () => {
    const response = await fetch('http://localhost:3000/api/health', {
      signal: AbortSignal.timeout(5000),
    });
    if (!response.ok) throw new Error('App failed');
  });
}
console.log(
  'Signaling: check browser Network for WSS 101. Media: check selected ICE pair, increasing inbound audio counters and human speech. These are pending manual checks.',
);

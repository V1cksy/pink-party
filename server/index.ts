import { RoomServiceClient } from 'livekit-server-sdk';
import { loadSettings, LIVEKIT_HTTP, WEB_PORT } from './config.ts';
import { readSession } from './session.ts';
import { createApp } from './app.ts';

try {
  const settings = loadSettings(process.env);
  const voice = new RoomServiceClient(
    LIVEKIT_HTTP,
    settings.apiKey,
    settings.apiSecret,
    { requestTimeout: 5 },
  );
  const server = createApp({
    settings,
    voice,
    session: await readSession(),
    health: () => voice.listRooms(),
  });
  server.on('error', (error: NodeJS.ErrnoException) => {
    console.error(
      error.code === 'EADDRINUSE'
        ? 'Port 3000 is in use. Stop the other application before starting Pink Party.'
        : 'Unable to start the local application server.',
    );
    process.exitCode = 1;
  });
  server.listen(WEB_PORT, '127.0.0.1', () =>
    console.log('Pink Party → http://localhost:3000'),
  );
  for (const signal of ['SIGINT', 'SIGTERM'] as const)
    process.on(signal, () => {
      server.close();
      server.closeAllConnections();
    });
} catch (error) {
  console.error(
    error instanceof Error ? error.message : 'Application startup failed.',
  );
  process.exitCode = 1;
}

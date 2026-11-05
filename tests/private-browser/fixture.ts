// Synthetic HTTPS/identity proxy for integration tests. This is not Tailscale.
import { createServer } from 'node:https';
import { request, type IncomingMessage } from 'node:http';
import type { Duplex } from 'node:stream';
import { readFile, mkdir } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { RoomServiceClient } from 'livekit-server-sdk';
import { createApp } from '../../server/app.ts';
import { loadSettings, LIVEKIT_HTTP } from '../../server/config.ts';
import { readSession } from '../../server/session.ts';

const local = loadSettings(process.env);
const settings = {
  ...local,
  joinCode: '',
  privateAccess: {
    origin: 'https://localhost:3443',
    tailscaleIp: '100.100.100.100',
    logins: ['peach@example.com', 'berry@example.com'],
  },
};
await mkdir('.local', { recursive: true, mode: 0o700 });
execFileSync(
  'openssl',
  [
    'req',
    '-x509',
    '-newkey',
    'rsa:2048',
    '-nodes',
    '-keyout',
    '.local/test-key.pem',
    '-out',
    '.local/test-cert.pem',
    '-days',
    '1',
    '-subj',
    '/CN=localhost',
    '-addext',
    'subjectAltName=DNS:localhost',
  ],
  { stdio: 'ignore' },
);
const voice = new RoomServiceClient(
  LIVEKIT_HTTP,
  settings.apiKey,
  settings.apiSecret,
  { requestTimeout: 3 },
);
const app = createApp({
  settings,
  voice,
  session: await readSession(),
  health: () => voice.listRooms(),
});
await new Promise<void>((resolve) => app.listen(0, '127.0.0.1', resolve));
const address = app.address();
if (!address || typeof address === 'string') throw new Error('No app address');
const port = address.port;
const sockets = new Set<Duplex>();
function forward(req: IncomingMessage) {
  return request({
    hostname: '127.0.0.1',
    port,
    path: req.url,
    method: req.method,
    headers: {
      ...req.headers,
      host: 'localhost:3443',
      // Deliberately replace incoming identity, as Serve is documented to do.
      'tailscale-user-login': String(
        req.headers['x-test-login'] ?? 'peach@example.com',
      ),
    },
  });
}
const proxy = createServer(
  {
    key: await readFile('.local/test-key.pem'),
    cert: await readFile('.local/test-cert.pem'),
  },
  (req, res) => {
    const upstream = forward(req);
    upstream.on('response', (reply) => {
      res.writeHead(reply.statusCode!, reply.headers);
      reply.pipe(res);
    });
    upstream.on('error', () => {
      res.writeHead(502);
      res.end();
    });
    req.pipe(upstream);
  },
);
proxy.on('connection', (socket) => {
  sockets.add(socket);
  socket.on('close', () => sockets.delete(socket));
});
proxy.on('upgrade', (req, client, head) => {
  const upstream = forward(req);
  upstream.on('error', () => client.destroy());
  upstream.on('response', (res) => {
    client.end(
      `HTTP/1.1 ${res.statusCode} Rejected\r\nConnection: close\r\n\r\n`,
    );
  });
  upstream.on('upgrade', (res, socket, extra) => {
    client.write(
      'HTTP/1.1 101 Switching Protocols\r\n' +
        Object.entries(res.headers)
          .map(([key, value]) => `${key}: ${value}`)
          .join('\r\n') +
        '\r\n\r\n',
    );
    if (extra.length) client.write(extra);
    if (head.length) socket.write(head);
    client.pipe(socket).pipe(client);
    socket.on('error', () => client.destroy());
    client.on('error', () => socket.destroy());
    client.on('close', () => socket.destroy());
    socket.on('close', () => client.destroy());
  });
  upstream.end();
});
proxy.listen(3443, '127.0.0.1');
for (const signal of ['SIGTERM', 'SIGINT'] as const)
  process.on(signal, () => {
    for (const socket of sockets) socket.destroy();
    proxy.closeAllConnections();
    proxy.close();
    app.closeAllConnections();
    app.close();
  });

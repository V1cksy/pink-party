import { request } from 'node:http';
import type { IncomingMessage, ServerResponse } from 'node:http';
import type { Duplex } from 'node:stream';
import { LIVEKIT_HTTP } from './config.ts';
import { HttpError } from './admission.ts';

export function signalingPath(req: IncomingMessage) {
  const url = new URL(req.url ?? '/', 'http://localhost');
  if (
    req.method !== 'GET' ||
    ![
      '/livekit/rtc',
      '/livekit/rtc/validate',
      '/livekit/rtc/v1',
      '/livekit/rtc/v1/validate',
    ].includes(url.pathname)
  )
    throw new HttpError(404, 'Not found.');
  if (req.headers.upgrade && !req.headers.origin)
    throw new HttpError(403, 'Signaling requires the Pink Party page origin.');
  return url.pathname.slice('/livekit'.length) + url.search;
}

function upstream(req: IncomingMessage, path: string) {
  return request(LIVEKIT_HTTP + path, {
    method: 'GET',
    headers: {
      ...(req.headers.origin ? { origin: req.headers.origin } : {}),
      ...(req.headers.upgrade
        ? {
            connection: 'Upgrade',
            upgrade: 'websocket',
            'sec-websocket-key': req.headers['sec-websocket-key'] ?? '',
            'sec-websocket-version':
              req.headers['sec-websocket-version'] ?? '13',
            ...(req.headers['sec-websocket-protocol']
              ? {
                  'sec-websocket-protocol':
                    req.headers['sec-websocket-protocol'],
                }
              : {}),
          }
        : {}),
    },
  });
}

export function proxySignaling(req: IncomingMessage, res: ServerResponse) {
  const proxy = upstream(req, signalingPath(req));
  proxy.setTimeout(5000, () => proxy.destroy());
  proxy.on('response', (response) => {
    res.writeHead(response.statusCode ?? 502, {
      'Content-Type': response.headers['content-type'] ?? 'text/plain',
      'Cache-Control': 'no-store',
    });
    response.on('error', () => res.destroy());
    response.pipe(res);
  });
  proxy.on('error', () => {
    if (!res.headersSent) res.writeHead(502);
    res.end('Voice signaling unavailable.');
  });
  res.on('close', () => proxy.destroy());
  proxy.end();
}

export function proxyUpgrade(
  req: IncomingMessage,
  client: Duplex,
  head: Buffer,
) {
  const proxy = upstream(req, signalingPath(req));
  const deadline = setTimeout(() => proxy.destroy(), 5000);
  let media: Duplex | undefined;
  const close = () => {
    clearTimeout(deadline);
    proxy.destroy();
    media?.destroy();
    client.destroy();
  };
  client.on('error', close);
  client.on('close', close);
  proxy.on('error', close);
  proxy.on('response', close);
  proxy.on('upgrade', (response, socket, upstreamHead) => {
    clearTimeout(deadline);
    media = socket;
    socket.on('error', close);
    socket.on('close', close);
    if (client.destroyed || response.statusCode !== 101) return close();
    const headers = [
      'HTTP/1.1 101 Switching Protocols',
      'Connection: Upgrade',
      'Upgrade: websocket',
    ];
    for (const key of [
      'sec-websocket-accept',
      'sec-websocket-protocol',
      'sec-websocket-extensions',
    ]) {
      if (typeof response.headers[key] === 'string')
        headers.push(`${key}: ${response.headers[key]}`);
    }
    client.write(headers.join('\r\n') + '\r\n\r\n');
    if (upstreamHead.length) client.write(upstreamHead);
    if (head.length) socket.write(head);
    client.pipe(socket).pipe(client);
  });
  proxy.end();
}

import { createServer } from 'node:http';
import type { IncomingMessage, ServerResponse } from 'node:http';
import { readFile } from 'node:fs/promises';
import { resolve, extname, sep } from 'node:path';
import { HttpError, issueVoiceToken } from './admission.ts';
import type { VoiceService } from './admission.ts';
import type { Settings } from './config.ts';
import type { Session } from './session.ts';
import { voiceUrl } from './config.ts';
import { checkAccess } from './access.ts';
import { proxySignaling, proxyUpgrade } from './signaling.ts';
import type { Duplex } from 'node:stream';

const contentTypes: Record<string, string> = {
  '.html': 'text/html; charset=utf-8',
  '.js': 'text/javascript',
  '.css': 'text/css',
  '.svg': 'image/svg+xml',
  '.ico': 'image/x-icon',
  '.woff2': 'font/woff2',
};

async function readBody(req: IncomingMessage): Promise<unknown> {
  if (req.headers['content-type']?.split(';')[0] !== 'application/json')
    throw new HttpError(415, 'Send JSON.');
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of req.iterator({ destroyOnReturn: false })) {
    size += chunk.length;
    if (size > 2048) {
      req.resume();
      throw new HttpError(413, 'Join request is too large.');
    }
    chunks.push(chunk);
  }
  try {
    return JSON.parse(Buffer.concat(chunks).toString('utf8'));
  } catch {
    throw new HttpError(400, 'Invalid JSON.');
  }
}

function json(res: ServerResponse, status: number, data: unknown) {
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Cache-Control': 'no-store',
  });
  res.end(JSON.stringify(data));
}

export function createApp(options: {
  settings: Settings;
  voice: VoiceService;
  session: Session;
  health: () => Promise<unknown>;
  dist?: string;
}) {
  const dist = resolve(options.dist ?? 'dist');
  let windowStart = Date.now();
  let attempts = 0;
  let inFlight = 0;
  const sockets = new Set<Duplex>();
  const server = createServer(async (req, res) => {
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('Referrer-Policy', 'no-referrer');
    res.setHeader('Permissions-Policy', 'camera=(), microphone=(self)');
    res.setHeader(
      'Content-Security-Policy',
      `default-src 'self'; script-src 'self'; style-src 'self'; connect-src 'self' ${voiceUrl(options.settings)}; media-src 'self' blob:; worker-src 'self' blob:; img-src 'self' data:; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'`,
    );
    try {
      const login = checkAccess(req, options.settings);
      const path = new URL(req.url ?? '/', 'http://localhost').pathname;
      if (options.settings.privateAccess && path.startsWith('/livekit/'))
        return proxySignaling(req, res);
      if (req.method === 'GET' && path === '/api/access')
        return json(res, 200, {
          mode: options.settings.privateAccess ? 'private' : 'local',
        });
      if (req.method === 'GET' && path === '/api/session')
        return json(res, 200, options.session);
      if (req.method === 'GET' && path === '/api/health') {
        try {
          await options.health();
          return json(res, 200, { status: 'ok', voice: 'ready' });
        } catch {
          return json(res, 503, { status: 'degraded', voice: 'unavailable' });
        }
      }
      if (req.method === 'POST' && path === '/api/voice-token') {
        if (!req.headers.origin)
          throw new HttpError(403, 'Join from the configured Pink Party page.');
        if (Date.now() - windowStart >= 60_000) {
          windowStart = Date.now();
          attempts = 0;
        }
        if (++attempts > 60 || inFlight >= 8)
          throw new HttpError(
            429,
            'Too many join attempts. Wait a minute and try again.',
          );
        inFlight++;
        try {
          return json(
            res,
            200,
            await issueVoiceToken(
              await readBody(req),
              options.settings,
              options.voice,
              login,
            ),
          );
        } finally {
          inFlight--;
        }
      }
      if (
        path.startsWith('/api/') ||
        !['GET', 'HEAD'].includes(req.method ?? '')
      )
        throw new HttpError(404, 'Not found.');
      const file = resolve(
        dist,
        '.' + decodeURIComponent(path === '/' ? '/index.html' : path),
      );
      if (!file.startsWith(dist + sep)) throw new HttpError(404, 'Not found.');
      try {
        const data = await readFile(file);
        res.writeHead(200, {
          'Content-Type':
            contentTypes[extname(file)] ?? 'application/octet-stream',
          'Cache-Control': 'no-cache',
        });
        res.end(req.method === 'HEAD' ? undefined : data);
      } catch (error) {
        if (
          (error as NodeJS.ErrnoException).code === 'ENOENT' ||
          (error as NodeJS.ErrnoException).code === 'EISDIR'
        )
          throw new HttpError(
            404,
            'Page not found. Run npm run build if this is a fresh checkout.',
          );
        throw error;
      }
    } catch (error) {
      if (res.destroyed) return;
      if (error instanceof HttpError)
        return json(res, error.status, { error: error.message });
      console.error(
        'Application request failed. Check local configuration and session data.',
      );
      json(res, 500, {
        error: 'Application error. Check the terminal and restart the app.',
      });
    }
  });
  server.on('upgrade', (req, socket, head) => {
    try {
      checkAccess(req, options.settings);
      if (!options.settings.privateAccess)
        throw new HttpError(403, 'Private signaling is disabled.');
      sockets.add(socket);
      socket.on('close', () => sockets.delete(socket));
      proxyUpgrade(req, socket, head);
    } catch (error) {
      const status = error instanceof HttpError ? error.status : 500;
      socket.end(`HTTP/1.1 ${status} Rejected\r\nConnection: close\r\n\r\n`);
    }
  });
  // HTTP closeAllConnections does not include upgraded WebSocket sockets.
  const closeHttp = server.closeAllConnections.bind(server);
  server.closeAllConnections = () => {
    closeHttp();
    for (const socket of sockets) socket.destroy();
  };
  server.requestTimeout = 10_000;
  server.headersTimeout = 10_000;
  server.timeout = 15_000;
  return server;
}

import type { IncomingMessage } from 'node:http';
import type { Settings } from './config.ts';
import { HttpError } from './admission.ts';

// Serve removes client-supplied identity headers. Only this loopback proxy
// listener trusts the replacement. Programs on the host remain trusted.
export function checkAccess(
  req: IncomingMessage,
  settings: Settings,
): string | undefined {
  const access = settings.privateAccess;
  const remote = req.socket.remoteAddress;
  if (remote !== '127.0.0.1')
    throw new HttpError(403, 'Use the configured Pink Party address.');
  const hosts = access
    ? [new URL(access.origin).host]
    : ['localhost:3000', '127.0.0.1:3000'];
  if (!hosts.includes(req.headers.host ?? ''))
    throw new HttpError(403, 'Use the configured Pink Party address.');
  const origins = access
    ? [access.origin]
    : [
        'http://localhost:3000',
        'http://127.0.0.1:3000',
        'http://localhost:5173',
        'http://127.0.0.1:5173',
      ];
  if (req.headers.origin && !origins.includes(req.headers.origin))
    throw new HttpError(403, 'Request origin is not allowed.');
  const identityHeaders = Object.keys(req.headers).filter(
    (key) =>
      key.startsWith('tailscale-') ||
      key.startsWith('x-forwarded-') ||
      key === 'forwarded',
  );
  if (!access) {
    if (identityHeaders.length)
      throw new HttpError(403, 'Proxy requests are disabled in local mode.');
    return undefined;
  }
  const login = req.headers['tailscale-user-login'];
  if (typeof login !== 'string' || !access.logins.includes(login))
    throw new HttpError(
      403,
      'This Tailscale account is not invited. Ask the host to check the private allowlist.',
    );
  return login;
}

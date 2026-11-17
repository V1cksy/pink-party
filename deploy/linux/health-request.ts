import { readFile } from 'node:fs/promises';
import { loadSettings } from '../../server/config.ts';
import { get } from 'node:http';

// The local root monitor uses this identity only at the trusted loopback boundary.
// It is not a Serve, TLS or remote-identity check and contains no application secrets.
export function monitorHeaders(value: unknown): Record<string, string> {
  if (!value || typeof value !== 'object')
    throw new Error('Invalid health request configuration');
  const entry = value as Record<string, unknown>;
  if (
    Object.keys(entry).sort().join(',') !== 'login,origin' ||
    typeof entry.origin !== 'string' ||
    typeof entry.login !== 'string'
  )
    throw new Error('Invalid health request configuration');
  const settings = loadSettings({
    PINK_PARTY_MODE: 'private',
    PUBLIC_ORIGIN: entry.origin,
    TAILSCALE_IP: '100.100.100.100',
    INVITED_LOGINS: entry.login,
    LIVEKIT_API_KEY: 'synthetic-health-key',
    LIVEKIT_API_SECRET: 'synthetic-health-validation-secret-32',
  });
  if (
    settings.privateAccess?.logins.length !== 1 ||
    settings.privateAccess.logins[0] !== entry.login
  )
    throw new Error('Use one exact login for the local monitor.');
  return {
    Host: new URL(entry.origin).host,
    'Tailscale-User-Login': entry.login,
  };
}

export function requestHealth(headers: Record<string, string>, port = 3000) {
  // Node's fetch omits an overridden Host. The private access boundary requires it.
  return new Promise<Response>((resolve, reject) => {
    const request = get(
      {
        hostname: '127.0.0.1',
        port,
        path: '/api/health',
        headers,
        signal: AbortSignal.timeout(1000),
      },
      (response) => {
        const chunks: Buffer[] = [];
        let size = 0;
        response.on('data', (chunk: Buffer) => {
          size += chunk.length;
          if (size > 2048) {
            const error = new Error('Health response exceeds size limit');
            reject(error);
            request.destroy(error);
          } else chunks.push(chunk);
        });
        response.on('error', reject);
        response.on('end', () =>
          resolve(
            new Response(Buffer.concat(chunks), {
              status: response.statusCode ?? 502,
            }),
          ),
        );
      },
    );
    request.on('error', reject);
  });
}

export async function healthRequest() {
  let headers: Record<string, string> = {};
  try {
    const data = await readFile('/etc/pink-party-monitor/request.json', 'utf8');
    if (data.length > 4096)
      throw new Error('Health request configuration too large');
    headers = monitorHeaders(JSON.parse(data));
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'ENOENT') throw error;
  }
  return requestHealth(headers);
}

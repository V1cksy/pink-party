export const ROOM_NAME = 'pink-party';
export const MAX_PARTICIPANTS = 4;
export const TOKEN_TTL_SECONDS = 60;
export const WEB_PORT = 3000;
export const LIVEKIT_HTTP = 'http://127.0.0.1:7880';
export const LIVEKIT_WS = 'ws://127.0.0.1:7880';

export interface PrivateAccess {
  origin: string;
  tailscaleIp: string;
  logins: string[];
}
export interface Settings {
  joinCode: string;
  apiKey: string;
  apiSecret: string;
  privateAccess?: PrivateAccess;
}

export function loadSettings(env: NodeJS.ProcessEnv): Settings {
  const mode = env.PINK_PARTY_MODE ?? 'local';
  if (!['local', 'private'].includes(mode))
    throw new Error('PINK_PARTY_MODE must be local or private.');
  const joinCode = env.JOIN_CODE ?? '';
  const apiKey = env.LIVEKIT_API_KEY ?? '';
  const apiSecret = env.LIVEKIT_API_SECRET ?? '';
  const secrets =
    mode === 'local' ? [joinCode, apiKey, apiSecret] : [apiKey, apiSecret];
  if (
    (mode === 'local' && (joinCode.length < 16 || joinCode.length > 128)) ||
    apiKey.length < 12 ||
    apiSecret.length < 32 ||
    secrets.some(
      (value) =>
        !/^[a-zA-Z0-9_-]+$/.test(value) || value.startsWith('replace-'),
    )
  )
    throw new Error(
      'Missing or invalid secrets. Run npm run setup; see .env.example.',
    );
  if (mode === 'local') {
    if (env.PUBLIC_ORIGIN || env.TAILSCALE_IP || env.INVITED_LOGINS)
      throw new Error('Private settings require PINK_PARTY_MODE=private.');
    return { joinCode, apiKey, apiSecret };
  }
  if (joinCode) throw new Error('Private mode must not contain JOIN_CODE.');
  const origin = env.PUBLIC_ORIGIN ?? '';
  if (
    !/^https:\/\/[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.[a-z0-9-]+\.ts\.net$/.test(
      origin,
    )
  )
    throw new Error(
      'PUBLIC_ORIGIN must be the exact https://machine.tailnet.ts.net origin, without a path or port.',
    );
  const tailscaleIp = env.TAILSCALE_IP ?? '';
  const octets = tailscaleIp.split('.').map(Number);
  if (
    !/^\d+\.\d+\.\d+\.\d+$/.test(tailscaleIp) ||
    octets.some((n) => n > 255) ||
    octets[0] !== 100 ||
    octets[1] < 64 ||
    octets[1] > 127 ||
    octets.join('.') !== tailscaleIp
  )
    throw new Error('TAILSCALE_IP must be this Mac’s Tailscale IPv4 address.');
  const logins = (env.INVITED_LOGINS ?? '').split(',').map((s) => s.trim());
  if (
    !logins.length ||
    logins.length > 6 ||
    logins.some(
      (s) => !/^[a-zA-Z0-9.!#$%&'*+/=?^_`{|}~-]+@[a-zA-Z0-9.-]+$/.test(s),
    )
  )
    throw new Error(
      'INVITED_LOGINS needs 1–6 exact, comma-separated Tailscale login names.',
    );
  return {
    joinCode: '',
    apiKey,
    apiSecret,
    privateAccess: { origin, tailscaleIp, logins },
  };
}

export function voiceUrl(settings: Settings) {
  return settings.privateAccess
    ? settings.privateAccess.origin.replace('https:', 'wss:') + '/livekit'
    : LIVEKIT_WS;
}

export function livekitConfig(settings: Settings) {
  const ip = settings.privateAccess?.tailscaleIp ?? '127.0.0.1';
  return `port: 7880
bind_addresses: [127.0.0.1]
rtc:
  node_ip: ${ip}
  use_external_ip: false
  enable_loopback_candidate: ${!settings.privateAccess}
  tcp_port: 0
  udp_port: 7882
  ips:
    includes: [${ip}/32]
  stun_servers: []
room:
  auto_create: false
  max_participants: ${MAX_PARTICIPANTS}
turn:
  enabled: false
keys:
  ${settings.apiKey}: ${settings.apiSecret}
logging:
  level: error
`;
}

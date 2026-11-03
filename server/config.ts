export const ROOM_NAME = 'pink-party';
export const MAX_PARTICIPANTS = 4;
export const TOKEN_TTL_SECONDS = 60;
export const WEB_PORT = 3000;
export const LIVEKIT_HTTP = 'http://127.0.0.1:7880';
export const LIVEKIT_WS = 'ws://127.0.0.1:7880';

export interface Settings {
  joinCode: string;
  apiKey: string;
  apiSecret: string;
}

export function loadSettings(env: NodeJS.ProcessEnv): Settings {
  const {
    JOIN_CODE: joinCode,
    LIVEKIT_API_KEY: apiKey,
    LIVEKIT_API_SECRET: apiSecret,
  } = env;
  if (
    !joinCode ||
    joinCode.length < 16 ||
    joinCode.length > 128 ||
    !apiKey ||
    apiKey.length < 12 ||
    !apiSecret ||
    apiSecret.length < 32 ||
    [joinCode, apiKey, apiSecret].some(
      (value) =>
        !/^[a-zA-Z0-9_-]+$/.test(value) || value.startsWith('replace-'),
    )
  ) {
    throw new Error(
      'Missing or invalid local secrets. Run npm run setup, or use random URL-safe values in .env (join code ≥16, API key ≥12, secret ≥32 characters).',
    );
  }
  return { joinCode, apiKey, apiSecret };
}

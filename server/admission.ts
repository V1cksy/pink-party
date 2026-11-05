import { createHash, randomUUID, timingSafeEqual } from 'node:crypto';
import { AccessToken, TrackSource } from 'livekit-server-sdk';
import type { Settings } from './config.ts';
import {
  ROOM_NAME,
  MAX_PARTICIPANTS,
  TOKEN_TTL_SECONDS,
  voiceUrl,
} from './config.ts';

export class HttpError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function validateName(body: unknown): string {
  if (!body || typeof body !== 'object' || Array.isArray(body))
    throw new HttpError(400, 'Enter a display name.');
  const { displayName } = body as Record<string, unknown>;
  if (
    typeof displayName !== 'string' ||
    !displayName.trim() ||
    [...displayName.trim()].length > 32 ||
    /[\p{Cc}\p{Cf}<>]/u.test(displayName)
  ) {
    throw new HttpError(
      400,
      'Use a display name of 1–32 characters without control characters or angle brackets.',
    );
  }
  return displayName.trim();
}

export function validateAdmission(body: unknown, expectedCode: string): string {
  const name = validateName(body);
  const { joinCode } = body as Record<string, unknown>;
  if (
    typeof joinCode !== 'string' ||
    joinCode.length > 128 ||
    !timingSafeEqual(
      createHash('sha256').update(joinCode).digest(),
      createHash('sha256').update(expectedCode).digest(),
    )
  )
    throw new HttpError(
      403,
      'That join code did not match. Check your local .env file.',
    );
  return name;
}

export interface VoiceService {
  createRoom(options: {
    name: string;
    maxParticipants: number;
    emptyTimeout: number;
    departureTimeout: number;
  }): Promise<unknown>;
  listParticipants(room: string): Promise<unknown[]>;
}

export async function issueVoiceToken(
  body: unknown,
  settings: Settings,
  voice: VoiceService,
  verifiedLogin?: string,
) {
  if (
    settings.privateAccess &&
    (!verifiedLogin || !settings.privateAccess.logins.includes(verifiedLogin))
  )
    throw new HttpError(
      403,
      'A verified invited Tailscale identity is required.',
    );
  const name = settings.privateAccess
    ? validateName(body)
    : validateAdmission(body, settings.joinCode);
  try {
    await voice.createRoom({
      name: ROOM_NAME,
      maxParticipants: MAX_PARTICIPANTS,
      emptyTimeout: 300,
      departureTimeout: 20,
    });
    if ((await voice.listParticipants(ROOM_NAME)).length >= MAX_PARTICIPANTS)
      throw new HttpError(
        409,
        'The room is full (4 people). Try again after someone leaves.',
      );
  } catch (error) {
    if (error instanceof HttpError) throw error;
    throw new HttpError(
      503,
      'Voice server unavailable. Restart npm start, then try joining again.',
    );
  }
  const token = new AccessToken(settings.apiKey, settings.apiSecret, {
    identity: randomUUID(),
    name,
    ttl: TOKEN_TTL_SECONDS,
  });
  token.addGrant({
    roomJoin: true,
    room: ROOM_NAME,
    canSubscribe: true,
    canPublish: true,
    canPublishSources: [TrackSource.MICROPHONE],
    canPublishData: false,
    canUpdateOwnMetadata: false,
  });
  return { token: await token.toJwt(), url: voiceUrl(settings) };
}

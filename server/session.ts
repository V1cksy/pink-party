import { readFile } from 'node:fs/promises';

export interface Session {
  game: string;
  title: string;
  description: string;
  startsAt: string;
  timeZone: string;
  tag: string;
  synthetic: true;
}

export function validateSession(value: unknown): Session {
  if (!value || typeof value !== 'object')
    throw new Error('Session must be an object.');
  const data = value as Record<string, unknown>;
  for (const key of [
    'game',
    'title',
    'description',
    'startsAt',
    'timeZone',
    'tag',
  ]) {
    if (
      typeof data[key] !== 'string' ||
      !data[key].trim() ||
      data[key].length > 500
    )
      throw new Error(`Invalid session field: ${key}`);
  }
  if (
    data.synthetic !== true ||
    !/T.*(Z|[+-]\d{2}:\d{2})$/.test(data.startsAt as string) ||
    !Number.isFinite(Date.parse(data.startsAt as string))
  ) {
    throw new Error(
      'Session needs synthetic: true and an ISO time with an offset.',
    );
  }
  new Intl.DateTimeFormat('en', { timeZone: data.timeZone as string });
  return data as unknown as Session;
}

export async function readSession(
  path = new URL('../data/session.json', import.meta.url),
): Promise<Session> {
  return validateSession(JSON.parse(await readFile(path, 'utf8')));
}

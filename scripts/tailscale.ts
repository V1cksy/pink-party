import { execFile } from 'node:child_process';
import { promisify } from 'node:util';
import { access } from 'node:fs/promises';
import type { PrivateAccess } from '../server/config.ts';

const run = promisify(execFile);
export async function tailscale(args: string[]) {
  const binary = await tailscaleBinary();
  try {
    return (
      await run(binary, args, { timeout: 15_000, maxBuffer: 2 * 1024 * 1024 })
    ).stdout;
  } catch {
    throw new Error(
      'Tailscale command failed. Check the native client or Linux tailscaled service and sign-in state in your own terminal.',
    );
  }
}

export function deviceFromStatus(status: any) {
  if (status.BackendState !== 'Running' || !status.Self?.Online)
    throw new Error('Tailscale must be connected and signed in.');
  const dns = status.Self.DNSName?.replace(/\.$/, '');
  const ip = status.Self.TailscaleIPs?.find((value: string) =>
    value.includes('.'),
  );
  if (!dns || !ip)
    throw new Error('Cannot discover this device’s Tailscale DNS and IPv4.');
  return { origin: `https://${dns}`, ip: ip as string };
}

export async function deviceStatus() {
  return deviceFromStatus(JSON.parse(await tailscale(['status', '--json'])));
}

export async function networkStatus() {
  const raw = JSON.parse(await tailscale(['status', '--json']));
  const status = deviceFromStatus(raw);
  const login = raw.User?.[raw.Self.UserID]?.LoginName;
  if (!login)
    throw new Error(
      'Cannot discover this device’s Tailscale DNS, IPv4 and owner login. Use an untagged signed-in device.',
    );
  return { ...status, login: login as string };
}

export async function verifyPrivateNetwork(config: PrivateAccess) {
  const status = await deviceStatus();
  if (config.origin !== status.origin || config.tailscaleIp !== status.ip)
    throw new Error(
      'Private configuration differs from the connected Tailscale device. Regenerate it using this host’s private-access guide.',
    );
}

export function assertServePortFree(config: unknown) {
  if (!config || typeof config !== 'object') return;
  const value = config as Record<string, unknown>;
  const tcp = value.TCP as Record<string, unknown> | undefined;
  const web = value.Web as Record<string, unknown> | undefined;
  const funnel = value.AllowFunnel as Record<string, unknown> | undefined;
  if (
    tcp?.['443'] ||
    Object.keys(web ?? {}).some((key) => key.endsWith(':443')) ||
    Object.values(funnel ?? {}).some(Boolean)
  )
    throw new Error(
      'Existing Serve configuration uses HTTPS 443 or enables Funnel. Kept it unchanged. Resolve the conflict before serving Pink Party.',
    );
  for (const child of Object.values(
    (value.Foreground ?? {}) as Record<string, unknown>,
  ))
    assertServePortFree(child);
}

export async function tailscaleBinary() {
  if (process.env.PINK_PARTY_TAILSCALE_BIN)
    return process.env.PINK_PARTY_TAILSCALE_BIN;
  const app = '/Applications/Tailscale.app/Contents/MacOS/Tailscale';
  return access(app).then(
    () => app,
    () => 'tailscale',
  );
}

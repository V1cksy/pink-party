import {
  readFile,
  writeFile,
  mkdir,
  rename,
  rm,
  lstat,
  mkdtemp,
} from 'node:fs/promises';
import { networkInterfaces } from 'node:os';
import { execFile } from 'node:child_process';
import { promisify, parseEnv } from 'node:util';
import { loadSettings } from '../../server/config.ts';
import {
  deviceStatus,
  assertServePortFree,
  tailscale,
} from '../../scripts/tailscale.ts';

const exec = promisify(execFile);
const envPath = '/etc/pink-party/pink-party.env';
const saved = '/etc/pink-party/before-private.env';
const request = '/etc/pink-party-monitor/request.json';
const override = '/etc/systemd/system/pink-party.service.d/50-private.conf';
async function absent(path: string) {
  await lstat(path).then(
    () => {
      throw new Error(
        'Existing private setup artifacts; inspect rollback before retrying.',
      );
    },
    (error: NodeJS.ErrnoException) => {
      if (error.code !== 'ENOENT') throw error;
    },
  );
}
async function rootFile(path: string) {
  const info = await lstat(path);
  if (
    !info.isFile() ||
    info.uid !== 0 ||
    (info.mode & 0o777) !== 0o600 ||
    info.size > 16384
  )
    throw new Error('Expected a root-owned regular file with mode 0600.');
  return readFile(path, 'utf8');
}
async function replaceEnv(data: string) {
  const directory = await mkdtemp('/etc/pink-party/.configure-');
  try {
    const temp = directory + '/environment';
    await writeFile(temp, data, { flag: 'wx', mode: 0o600 });
    await rename(temp, envPath);
  } finally {
    await rm(directory, { recursive: true, force: true });
  }
}
try {
  if (process.platform !== 'linux' || process.getuid?.() !== 0)
    throw new Error('Run as root on the deployed Linux host.');
  // Never take a snapshot while a timer or the application could be reading/writing it.
  for (const unit of [
    'pink-party.service',
    'pink-party-https.service',
    'pink-party-backup.timer',
    'pink-party-backup.service',
  ]) {
    const { stdout } = await exec(
      'systemctl',
      ['show', unit, '-p', 'ActiveState', '--value'],
      { timeout: 3000 },
    );
    if (!['inactive', 'failed', ''].includes(stdout.trim()))
      throw new Error(
        'Stop the application, HTTPS and backup units before configuration.',
      );
  }
  if (process.argv[2] === 'configure') {
    for (const path of [saved, request, override]) await absent(path);
    const original = await rootFile(envPath);
    const settings = loadSettings(parseEnv(original));
    if (settings.privateAccess)
      throw new Error('Private mode already configured.');
    const logins = (await rootFile(process.argv[3] ?? ''))
      .trim()
      .split(/\r?\n/)
      .map((line) => line.trim())
      .join(',');
    const device = await deviceStatus();
    if (!networkInterfaces().tailscale0?.some((n) => n.address === device.ip))
      throw new Error(
        'A native tailscale0 interface with the configured IPv4 is required.',
      );
    assertServePortFree(
      JSON.parse(await tailscale(['serve', 'status', '--json'])),
    );
    const fields = {
      PINK_PARTY_MODE: 'private',
      PUBLIC_ORIGIN: device.origin,
      TAILSCALE_IP: device.ip,
      INVITED_LOGINS: logins,
      LIVEKIT_API_KEY: settings.apiKey,
      LIVEKIT_API_SECRET: settings.apiSecret,
    };
    loadSettings(fields);
    await mkdir('/etc/pink-party-monitor', { recursive: true, mode: 0o700 });
    const directory = await lstat('/etc/pink-party-monitor');
    if (
      !directory.isDirectory() ||
      directory.uid !== 0 ||
      (directory.mode & 0o777) !== 0o700
    )
      throw new Error('Unsafe monitor request directory.');
    await mkdir('/etc/systemd/system/pink-party.service.d', {
      recursive: true,
      mode: 0o755,
    });
    await writeFile(saved, original, { flag: 'wx', mode: 0o600 });
    // A saved local configuration remains available if any later write fails.
    await writeFile(
      request,
      JSON.stringify({ origin: device.origin, login: logins.split(',')[0] }),
      { flag: 'wx', mode: 0o600 },
    );
    await writeFile(
      override,
      '[Unit]\nWants=tailscaled.service\nAfter=tailscaled.service network-online.target\n[Service]\nEnvironment=PATH=/opt/pink-party/node/bin:/opt/pink-party/bin:/usr/local/bin:/usr/bin:/bin\n',
      { flag: 'wx', mode: 0o644 },
    );
    await replaceEnv(
      Object.entries(fields)
        .map(([key, value]) => `${key}=${JSON.stringify(value)}\n`)
        .join(''),
    );
    console.log(
      'Private configuration prepared. Reload units, start the application and verify owned health before starting HTTPS.',
    );
  } else if (process.argv[2] === 'rollback') {
    const original = await rootFile(saved);
    if (loadSettings(parseEnv(original)).privateAccess)
      throw new Error('Rollback source must be local mode.');
    await replaceEnv(original);
    await rm(request, { force: true });
    await rm(override, { force: true });
    await rm(saved);
    console.log(
      'Original local configuration restored. Reload units and verify health before resuming backups.',
    );
  } else throw new Error('Use configure ROOT_ONLY_LOGINS_FILE or rollback.');
} catch {
  console.error(
    'Private configuration failed. Check stopped units, native Tailscale sign-in/interface, root-only input and saved rollback files. No secrets were printed.',
  );
  process.exitCode = 1;
}

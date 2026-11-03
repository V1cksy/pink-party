import { spawn } from 'node:child_process';
import type { ChildProcess } from 'node:child_process';
import { mkdir, writeFile, access } from 'node:fs/promises';
import { createServer } from 'node:net';
import { RoomServiceClient } from 'livekit-server-sdk';
import {
  loadSettings,
  LIVEKIT_HTTP,
  MAX_PARTICIPANTS,
} from '../server/config.ts';
import { readSession } from '../server/session.ts';

const children: ChildProcess[] = [];
let stopping = false;
function stop(code: number) {
  if (stopping) return;
  stopping = true;
  process.exitCode = code;
  for (const child of children) child.kill('SIGTERM');
  const timer = setTimeout(() => {
    for (const child of children)
      if (child.exitCode === null) child.kill('SIGKILL');
  }, 4000);
  timer.unref();
}
for (const signal of ['SIGINT', 'SIGTERM'] as const)
  process.on(signal, () => stop(0));

function launch(command: string, args: string[]) {
  const child = spawn(command, args, { stdio: 'inherit' });
  children.push(child);
  child.on('error', () => {
    console.error(
      `Cannot start ${command}. Install prerequisites from README.md.`,
    );
    stop(1);
  });
  child.on('exit', (code) => {
    if (!stopping) {
      console.error(`${command} stopped (exit ${code ?? 'signal'}).`);
      stop(1);
    }
  });
  return child;
}

async function assertFree(port: number) {
  await new Promise<void>((resolve, reject) => {
    const probe = createServer();
    probe.once('error', () =>
      reject(
        new Error(
          `Port ${port} is in use. Stop the other service, then retry npm start.`,
        ),
      ),
    );
    probe.listen(port, '127.0.0.1', () => probe.close(() => resolve()));
  });
}

try {
  const settings = loadSettings(process.env);
  await readSession();
  await access('dist/index.html').catch(() => {
    throw new Error('Built interface missing. Run npm run build first.');
  });
  await assertFree(3000);
  await assertFree(7880);
  await mkdir('.local', { recursive: true, mode: 0o700 });
  await writeFile(
    '.local/livekit.yaml',
    `port: 7880
bind_addresses: [127.0.0.1]
rtc:
  node_ip: 127.0.0.1
  use_external_ip: false
  enable_loopback_candidate: true
  tcp_port: 0
  udp_port: 7882
  ips:
    includes: [127.0.0.1/32]
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
`,
    { mode: 0o600 },
  );
  launch('livekit-server', ['--config', '.local/livekit.yaml']);
  const voice = new RoomServiceClient(
    LIVEKIT_HTTP,
    settings.apiKey,
    settings.apiSecret,
    { requestTimeout: 1 },
  );
  let ready = false;
  const readyDeadline = Date.now() + 10_000;
  while (Date.now() < readyDeadline && !stopping) {
    try {
      await voice.listRooms();
      ready = true;
      break;
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 250));
    }
  }
  if (!stopping && !ready)
    throw new Error(
      'LiveKit did not become ready during startup. Check its startup output and local ports.',
    );
  if (!stopping)
    launch(process.execPath, ['--env-file=.env', 'server/index.ts']);
} catch (error) {
  console.error(error instanceof Error ? error.message : 'Startup failed.');
  stop(1);
}

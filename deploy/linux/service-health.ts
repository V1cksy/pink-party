import { execFile } from 'node:child_process';
import { readFile } from 'node:fs/promises';
import { promisify } from 'node:util';
import { fileURLToPath } from 'node:url';

const exec = promisify(execFile);
export async function serviceListener(port: number): Promise<number> {
  const [socket, group] = await Promise.all([
    exec('ss', ['-H', '-ltnp', `sport = :${port}`], { timeout: 2000 }),
    exec(
      'systemctl',
      ['show', 'pink-party.service', '--property=ControlGroup', '--value'],
      { timeout: 2000 },
    ),
  ]);
  const pids = [
    ...new Set(
      [...socket.stdout.matchAll(/pid=(\d+)/g)].map((match) =>
        Number(match[1]),
      ),
    ),
  ];
  const cgroup = group.stdout.trim();
  if (pids.length !== 1 || !cgroup)
    throw new Error(`TCP ${port} is not owned by pink-party.service`);
  const membership = await readFile(`/proc/${pids[0]}/cgroup`, 'utf8');
  if (!membership.split('\n').includes(`0::${cgroup}`)) {
    throw new Error(`TCP ${port} is not owned by pink-party.service`);
  }
  return pids[0];
}

export type HealthObservation = {
  status: 'up' | 'down';
  reason:
    | 'web-control-ready'
    | 'service-not-active'
    | 'service-query-failed'
    | 'listener-not-owned'
    | 'health-request-failed';
};

export async function inspectServiceHealth(
  tools = {
    activeState: async () =>
      (
        await exec(
          'systemctl',
          ['show', 'pink-party.service', '--property=ActiveState', '--value'],
          { timeout: 2000 },
        )
      ).stdout.trim(),
    listener: serviceListener,
    request: () =>
      fetch('http://127.0.0.1:3000/api/health', {
        signal: AbortSignal.timeout(1000),
        redirect: 'error',
      }),
  },
): Promise<HealthObservation> {
  try {
    if ((await tools.activeState()) !== 'active')
      return { status: 'down', reason: 'service-not-active' };
  } catch {
    return { status: 'down', reason: 'service-query-failed' };
  }
  try {
    await tools.listener(3000);
    await tools.listener(7880);
  } catch {
    return { status: 'down', reason: 'listener-not-owned' };
  }
  try {
    const response = await tools.request();
    const body = await response.json();
    if (response.ok && body.status === 'ok' && body.voice === 'ready')
      return { status: 'up', reason: 'web-control-ready' };
  } catch {
    // Only fixed diagnostic codes leave this boundary; never response bodies.
  }
  return { status: 'down', reason: 'health-request-failed' };
}

export async function healthyService(): Promise<boolean> {
  return (await inspectServiceHealth()).status === 'up';
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  if (!(await healthyService())) process.exitCode = 1;
}

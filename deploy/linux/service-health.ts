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

export async function healthyService(): Promise<boolean> {
  try {
    await exec('systemctl', ['is-active', '--quiet', 'pink-party.service'], {
      timeout: 2000,
    });
    await serviceListener(3000);
    const response = await fetch('http://127.0.0.1:3000/api/health', {
      signal: AbortSignal.timeout(1000),
    });
    await response.body?.cancel();
    return response.ok;
  } catch {
    return false;
  }
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
  if (!(await healthyService())) process.exitCode = 1;
}

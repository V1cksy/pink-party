import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

export function tailscaleProcesses() {
  // On macOS, comm is truncated to 16 characters unless it is the last field.
  const lines = execFileSync('ps', ['-axo', 'pid=,comm='], {
    encoding: 'utf8',
  }).split('\n');
  const processes: { name: string; pid: string }[] = [];
  for (const line of lines) {
    const match = line.trim().match(/^(\d+)\s+(.+)$/);
    if (!match) continue;
    const [, pid, command] = match;
    if (command === '/Applications/Tailscale.app/Contents/MacOS/Tailscale') {
      const args = execFileSync('ps', ['-p', pid, '-o', 'args='], {
        encoding: 'utf8',
      });
      processes.push({
        name: args.includes(' serve ')
          ? 'Tailscale Serve CLI'
          : 'Tailscale app',
        pid,
      });
    }
    if (
      command.startsWith('/Library/SystemExtensions/') &&
      command.endsWith('/io.tailscale.ipn.macsys.network-extension')
    )
      processes.push({ name: 'Tailscale network extension', pid });
  }
  if (!processes.some((item) => item.name === 'Tailscale network extension'))
    throw new Error('Native Tailscale network extension not running.');
  const counts = new Map<string, number>();
  return processes.map((item) => {
    const count = (counts.get(item.name) ?? 0) + 1;
    counts.set(item.name, count);
    return { ...item, name: count === 1 ? item.name : `${item.name} ${count}` };
  });
}

export async function measureResources(
  label: string,
  seconds = 10,
  services = [
    { name: 'application', port: 3000 },
    { name: 'LiveKit', port: 7880 },
  ],
  additionalProcesses: { name: string; pid: string }[] = [],
) {
  const processes = services
    .map((item) => ({
      name: item.name,
      pid: execFileSync('lsof', ['-tiTCP:' + item.port, '-sTCP:LISTEN'], {
        encoding: 'utf8',
      }).trim(),
    }))
    .concat(additionalProcesses);
  const measurements: Record<
    string,
    { rssMiB: number; psCpuPercent: number }[]
  > = {};
  for (let i = 0; i < seconds; i++) {
    for (const process of processes) {
      const [rss, cpu] = execFileSync(
        'ps',
        ['-p', process.pid, '-o', 'rss=,%cpu='],
        { encoding: 'utf8' },
      )
        .trim()
        .split(/\s+/)
        .map(Number);
      (measurements[process.name] ??= []).push({
        rssMiB: rss / 1024,
        psCpuPercent: cpu,
      });
    }
    await new Promise((resolve) => setTimeout(resolve, 1000));
  }
  return {
    label,
    capturedAt: new Date().toISOString(),
    samples: seconds,
    intervalSeconds: 1,
    exclusions:
      'Browser processes, startup supervisor, npm, build tooling and other host applications. ' +
      (additionalProcesses.length
        ? 'Named Tailscale processes are included. '
        : 'Tailscale is excluded. ') +
      'ps %CPU is an OS estimate, not an interval profiler.',
    processes: Object.entries(measurements).map(([name, values]) => ({
      name,
      meanRssMiB: +(
        values.reduce((sum, x) => sum + x.rssMiB, 0) / values.length
      ).toFixed(2),
      peakRssMiB: +Math.max(...values.map((x) => x.rssMiB)).toFixed(2),
      meanPsCpuPercent: +(
        values.reduce((sum, x) => sum + x.psCpuPercent, 0) / values.length
      ).toFixed(2),
      peakPsCpuPercent: Math.max(...values.map((x) => x.psCpuPercent)),
    })),
  };
}
if (process.argv[1] === fileURLToPath(import.meta.url)) {
  const privateMode = process.argv[2] === '--private';
  const seconds = Number(process.argv[privateMode ? 3 : 2] ?? 10);
  if (!Number.isInteger(seconds) || seconds < 1 || seconds > 60)
    throw new Error('Choose a sample duration of 1–60 seconds.');
  console.log(
    JSON.stringify(
      await measureResources(
        privateMode
          ? 'manual private sample; record client count separately'
          : 'manual local sample',
        seconds,
        undefined,
        privateMode ? tailscaleProcesses() : [],
      ),
      null,
      2,
    ),
  );
}

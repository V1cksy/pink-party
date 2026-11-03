import { execFileSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';

export async function measureResources(label: string, seconds = 10) {
  const processes = [
    { name: 'application', port: 3000 },
    { name: 'LiveKit', port: 7880 },
  ].map((item) => ({
    ...item,
    pid: execFileSync('lsof', ['-tiTCP:' + item.port, '-sTCP:LISTEN'], {
      encoding: 'utf8',
    }).trim(),
  }));
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
      'Browser processes, startup supervisor, npm, build tooling and other host applications. ps %CPU is an OS estimate, not an interval profiler.',
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
  const seconds = Number(process.argv[2] ?? 10);
  if (!Number.isInteger(seconds) || seconds < 1 || seconds > 60)
    throw new Error('Choose a sample duration of 1–60 seconds.');
  console.log(
    JSON.stringify(
      await measureResources('manual local sample', seconds),
      null,
      2,
    ),
  );
}

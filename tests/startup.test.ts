import assert from 'node:assert/strict';
import { test } from 'node:test';
import { spawn } from 'node:child_process';
import { once } from 'node:events';
import { mkdtemp, mkdir, writeFile, access, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';

test(
  'shutdown during a slow Tailscale lookup cannot launch services afterward (injected network/tools)',
  { timeout: 15_000 },
  async (t) => {
    const dir = await mkdtemp(join(tmpdir(), 'pink-party-startup-'));
    t.after(() => rm(dir, { recursive: true, force: true }));
    await mkdir(join(dir, 'dist'));
    await writeFile(join(dir, 'dist/index.html'), 'fixture');
    const status = {
      BackendState: 'Running',
      Self: {
        Online: true,
        DNSName: 'hangout.example-tail.ts.net.',
        TailscaleIPs: ['100.100.100.100'],
        UserID: 1,
      },
      User: { '1': { LoginName: 'peach@example.com' } },
    };
    await writeFile(
      join(dir, 'tailscale'),
      `#!${process.execPath}\nimport { writeFileSync } from 'node:fs';\nwriteFileSync('lookup-started', '');\nsetTimeout(() => process.stdout.write(${JSON.stringify(JSON.stringify(status))}), 5500);\n`,
      { mode: 0o700 },
    );
    await writeFile(
      join(dir, 'livekit-server'),
      `#!${process.execPath}\nimport { writeFileSync } from 'node:fs';\nwriteFileSync('unexpected-service', '');\n`,
      { mode: 0o700 },
    );
    // Avoid requiring a real Tailscale interface or taking fixed ports in this test.
    const preload = join(dir, 'network-fixture.mjs');
    await writeFile(
      preload,
      `import os from 'node:os';\nimport net from 'node:net';\nimport { EventEmitter } from 'node:events';\nimport { syncBuiltinESMExports } from 'node:module';\nos.networkInterfaces = () => ({ fixture: [{ address: '100.100.100.100' }] });\nnet.createServer = () => Object.assign(new EventEmitter(), { listen(_port, _ip, callback) { queueMicrotask(callback); }, close(callback) { callback(); } });\nsyncBuiltinESMExports();\n`,
    );
    const child = spawn(
      process.execPath,
      [
        '--import',
        preload,
        fileURLToPath(new URL('../scripts/start.ts', import.meta.url)),
      ],
      {
        cwd: dir,
        stdio: 'pipe',
        env: {
          ...process.env,
          PATH: dir + ':' + process.env.PATH,
          PINK_PARTY_TAILSCALE_BIN: join(dir, 'tailscale'),
          PINK_PARTY_MODE: 'private',
          JOIN_CODE: '',
          PUBLIC_ORIGIN: 'https://hangout.example-tail.ts.net',
          TAILSCALE_IP: '100.100.100.100',
          INVITED_LOGINS: 'peach@example.com',
          LIVEKIT_API_KEY: 'synthetic-api-key',
          LIVEKIT_API_SECRET: 'synthetic-secret-with-at-least-32-characters',
        },
      },
    );
    t.after(() => child.kill('SIGKILL'));
    const exit = once(child, 'exit');
    const deadline = Date.now() + 3000;
    while (true) {
      if (
        await access(join(dir, 'lookup-started')).then(
          () => true,
          () => false,
        )
      )
        break;
      assert.ok(Date.now() < deadline, 'Fake Tailscale lookup did not start');
      await new Promise((resolve) => setTimeout(resolve, 20));
    }
    child.kill('SIGTERM');
    const [code] = await exit;
    assert.equal(code, 0);
    assert.equal(
      await access(join(dir, 'unexpected-service')).then(
        () => true,
        () => false,
      ),
      false,
      'A service launched after shutdown',
    );
  },
);

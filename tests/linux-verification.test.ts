import assert from 'node:assert/strict';
import { test } from 'node:test';
import { mkdtemp, writeFile, access, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { spawnSync } from 'node:child_process';

test('Linux verifier rejects invalid configuration before any service command (injected root/platform/tools)', async (t) => {
  const dir = await mkdtemp(join(tmpdir(), 'pink-party-linux-preflight-'));
  t.after(() => rm(dir, { recursive: true, force: true }));
  const marker = join(dir, 'unexpected-command');
  const preload = join(dir, 'preflight.mjs');
  await writeFile(
    preload,
    `import cp from 'node:child_process';
import { writeFileSync } from 'node:fs';
import { syncBuiltinESMExports } from 'node:module';
Object.defineProperty(process, 'platform', { value: 'linux' });
process.getuid = () => 0;
cp.execFile = (_file, _args, _options, callback) => {
  writeFileSync(${JSON.stringify(marker)}, '');
  queueMicrotask(() => callback(new Error('Fixture blocked a service command')));
};
cp.spawnSync = () => { writeFileSync(${JSON.stringify(marker)}, ''); throw new Error('Fixture blocked a synchronous command'); };
syncBuiltinESMExports();
`,
  );
  const result = spawnSync(
    process.execPath,
    [
      '--import',
      preload,
      fileURLToPath(new URL('../deploy/linux/verify.ts', import.meta.url)),
    ],
    {
      encoding: 'utf8',
      timeout: 5000,
      env: { ...process.env, PINK_PARTY_MODE: 'invalid-fixture-mode' },
    },
  );
  assert.equal(result.status, 1);
  assert.equal(
    await access(marker).then(
      () => true,
      () => false,
    ),
    false,
    'Rejected configuration attempted a service command',
  );
  assert.match(result.stderr, /PINK_PARTY_MODE must be local or private/);
});

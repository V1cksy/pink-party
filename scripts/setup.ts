import { randomBytes } from 'node:crypto';
import { writeFile } from 'node:fs/promises';

try {
  await writeFile(
    '.env',
    `# Local development secrets. Never commit this file.\nJOIN_CODE=${randomBytes(12).toString('hex')}\nLIVEKIT_API_KEY=${randomBytes(12).toString('hex')}\nLIVEKIT_API_SECRET=${randomBytes(32).toString('hex')}\n`,
    { mode: 0o600, flag: 'wx' },
  );
  console.log(
    'Created private .env. Read JOIN_CODE there when joining; it is never printed in logs.',
  );
} catch (error) {
  if ((error as NodeJS.ErrnoException).code === 'EEXIST')
    console.log('.env already exists; kept your configuration.');
  else throw error;
}

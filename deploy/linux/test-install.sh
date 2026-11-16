#!/usr/bin/env bash
set -euo pipefail
umask 077
if [[ $(id -u) != 0 || $(uname -m) != aarch64 ]]; then
  echo 'Run with sudo inside the deployed Linux VM.' >&2
  exit 1
fi
export PATH=/opt/pink-party/node/bin:/opt/pink-party/bin:/usr/sbin:/usr/bin:/sbin:/bin
work=$(mktemp -d /var/tmp/pink-party-install-check.XXXXXX)
trap 'rm -rf "$work"' EXIT
tar -C /opt/pink-party/app --exclude=node_modules --exclude=.local -cf - . | tar -C "$work" -xf -
printf 'SYNTHETIC_PRIVATE_SENTINEL=local-check-only\n' > "$work/.env"
cp "$work/.env" "$work/.env.private"
cp "$work/.env" "$work/scripts/.env.production"
mkdir "$work/.local"
cp "$work/.env" "$work/.local/private-sentinel"
before=$(sha256sum /etc/pink-party/pink-party.env)
pid=$(systemctl show pink-party.service --property=MainPID --value)
test "$pid" -gt 0
curl --fail --silent --max-time 2 http://127.0.0.1:3000/api/health >/dev/null

# Force a build failure before activation; the installed service must stay healthy.
node --input-type=module - "$work/package.json" <<'JS'
import { readFileSync, writeFileSync } from 'node:fs';
const path = process.argv[2];
const data = JSON.parse(readFileSync(path, 'utf8'));
data.scripts.build = 'node -e "console.error(\'PINK_PARTY_EXPECTED_BUILD_FAILURE\'); process.exit(17)"';
writeFileSync(path, JSON.stringify(data));
JS
if bash "$work/deploy/linux/install.sh" "$work" > "$work/failed-build.log" 2>&1; then
  echo 'Installer incorrectly accepted the deliberately failed build.' >&2
  exit 1
else
  failure_status=$?
fi
test "$failure_status" -eq 17
grep -q '^PINK_PARTY_EXPECTED_BUILD_FAILURE$' "$work/failed-build.log"
test "$(systemctl show pink-party.service --property=MainPID --value)" = "$pid"
curl --fail --silent --max-time 2 http://127.0.0.1:3000/api/health >/dev/null
cp /opt/pink-party/app/package.json "$work/package.json"

# A normal checkout can contain ignored credentials. They must not enter the app.
bash "$work/deploy/linux/install.sh" "$work" > "$work/redeploy.log" 2>&1
test "$(sha256sum /etc/pink-party/pink-party.env)" = "$before"
test ! -e /opt/pink-party/app/.env
test ! -e /opt/pink-party/app/.env.private
test ! -e /opt/pink-party/app/scripts/.env.production
test -L /opt/pink-party/app/.local
test "$(readlink /opt/pink-party/app/.local)" = /var/lib/pink-party
test ! -e /var/lib/pink-party/private-sentinel
test "$(systemctl show pink-party.service --property=MainPID --value)" != "$pid"
curl --fail --silent --max-time 2 http://127.0.0.1:3000/api/health >/dev/null
node --input-type=module <<'JS'
import { writeFileSync } from 'node:fs';
writeFileSync('/var/lib/pink-party/linux-install-validation.json', JSON.stringify({
  capturedAt: new Date().toISOString(),
  failedBuildPreservedRunningService: true,
  dirtySourcePrivateFilesExcluded: true,
  nestedPrivateEnvironmentExcluded: true,
  redeployedWhileServiceRunning: true,
  credentialsPreserved: true,
}, null, 2) + '\n', { mode: 0o600 });
JS
echo 'Build-failure isolation, dirty-source exclusions, live redeployment and credential preservation: OK'

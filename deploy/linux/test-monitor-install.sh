#!/usr/bin/env bash
set -euo pipefail
umask 077
if [[ $(id -u) != 0 || $(uname -m) != aarch64 ]]; then
  echo 'Run with sudo inside the deployed local Linux VM.' >&2
  exit 1
fi
export PATH=/opt/pink-party/node/bin:/opt/pink-party/bin:/usr/sbin:/usr/bin:/sbin:/bin
node /opt/pink-party/app/deploy/linux/service-health.ts
systemctl is-active --quiet pink-party-monitor.timer
work=$(mktemp -d /var/tmp/pink-party-monitor-install.XXXXXX)
restore=false
cleanup() {
  local result=$?
  if [[ $restore == true ]]; then
    if ! bash "$work/good/deploy/linux/install.sh" "$work/good" > "$work/recovery.log" 2>&1; then
      echo "Restore failed; inspect private files in $work." >&2
      exit 1
    fi
  fi
  rm -rf "$work"
  exit "$result"
}
trap cleanup EXIT
mkdir "$work/good" "$work/bad"
bash /opt/pink-party/app/deploy/linux/archive.sh /opt/pink-party/app "$work/source.tar"
tar -C "$work/good" -xf "$work/source.tar"
tar -C "$work/bad" -xf "$work/source.tar"
before=$(sha256sum /etc/pink-party/pink-party.env)
# The interface build succeeds, but the replacement backend cannot start.
printf 'console.error("PINK_PARTY_EXPECTED_ACTIVATION_FAILURE"); process.exit(17); export {};\n' > "$work/bad/server/index.ts"
fault_at=$(node -e 'console.log(new Date().toISOString())')
restore=true
if bash "$work/bad/deploy/linux/install.sh" "$work/bad" > "$work/failed-activation.log" 2>&1; then
  echo 'Installer incorrectly accepted the failed activation.' >&2
  exit 1
fi
systemctl is-active --quiet pink-party-monitor.timer
systemctl is-failed --quiet pink-party.service
failed_at=$(node -e 'console.log(new Date().toISOString())')
journalctl -u pink-party.service --since "$fault_at" --no-pager -o cat > "$work/service.log"
grep -q '^PINK_PARTY_EXPECTED_ACTIVATION_FAILURE$' "$work/service.log"
node --input-type=module - "$failed_at" <<'JS'
import assert from 'node:assert/strict';
import { readHistory } from '/opt/pink-party/app/deploy/linux/monitor.ts';
const deadline = performance.now() + 75000;
let detected = false;
while (performance.now() < deadline) {
  detected = (await readHistory()).some(row => row.observedAt > process.argv[2] && row.status === 'down');
  if (detected) break;
  await new Promise(resolve => setTimeout(resolve, 500));
}
assert.ok(detected, 'Scheduled monitor did not record the failed activation');
JS
bash "$work/good/deploy/linux/install.sh" "$work/good" > "$work/recovery.log" 2>&1
test "$(sha256sum /etc/pink-party/pink-party.env)" = "$before"
node /opt/pink-party/app/deploy/linux/service-health.ts
systemctl is-active --quiet pink-party-monitor.timer
restore=false
node --input-type=module <<'JS'
import { writeFileSync } from 'node:fs';
writeFileSync('/var/lib/pink-party-monitor/install-validation.json', JSON.stringify({
  capturedAt: new Date().toISOString(),
  failedActivationRejected: true,
  timerActiveDuringApplicationFailure: true,
  scheduledDownRecorded: true,
  normalApplicationRestored: true,
  credentialsPreserved: true,
}, null, 2) + '\n', { mode: 0o600 });
JS
echo 'Failed activation rejected; monitoring continued; normal application and credentials restored.'

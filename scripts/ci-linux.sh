#!/usr/bin/env bash
set -euo pipefail
umask 077

# This destructive cleanup belongs only to a fresh, disposable hosted-runner checkout.
if [[ ${GITHUB_ACTIONS:-} != true || ${RUNNER_OS:-} != Linux || ${RUNNER_ARCH:-} != ARM64 || $(uname -s) != Linux || $(uname -m) != aarch64 ]]; then
  echo 'Run this script only on the disposable Linux ARM64 GitHub Actions runner.' >&2
  exit 1
fi
cd "${GITHUB_WORKSPACE:?Missing runner workspace}"
if [[ -e .env || -L .env || -e .local || -L .local ]]; then
  echo 'CI requires a fresh checkout without local configuration or state.' >&2
  exit 1
fi
work=$(mktemp -d "${RUNNER_TEMP:?Missing runner temporary directory}/pink-party-ci.XXXXXX")
supervisor=
cleanup() {
  local result=$?
  trap - EXIT INT TERM
  if [[ -n $supervisor ]]; then
    kill -TERM -- "-$supervisor" 2>/dev/null || true
    sleep 2
    kill -KILL -- "-$supervisor" 2>/dev/null || true
    wait "$supervisor" 2>/dev/null || true
  fi
  rm -f .env
  rm -rf .local test-results "$work"
  exit "$result"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

sudo apt-get update -qq
sudo apt-get install -y --no-install-recommends age ca-certificates curl xz-utils libatomic1 python3 lsof openssh-sftp-server
test -x /usr/lib/openssh/sftp-server
. deploy/linux/runtimes.sh
fetch_runtime "$NODE_URL" "$work/node.tar.xz" "$NODE_SHA256"
fetch_runtime "$LIVEKIT_URL" "$work/livekit.tar.gz" "$LIVEKIT_SHA256"
mkdir "$work/node" "$work/bin"
tar -xJf "$work/node.tar.xz" --strip-components=1 -C "$work/node"
tar -xzf "$work/livekit.tar.gz" -C "$work/bin" livekit-server
export PATH="$work/node/bin:$work/bin:/usr/bin:/bin"
export PYTHONDONTWRITEBYTECODE=1
npm ci --no-audit --no-fund
npm run check
timeout 10m npx playwright install --with-deps chromium

# These keys exist only for this ephemeral loopback fixture. Mask accidental diagnostics too.
node scripts/setup.ts
node --env-file=.env --input-type=module -e '
  for (const name of ["JOIN_CODE", "LIVEKIT_API_KEY", "LIVEKIT_API_SECRET"])
    console.log(`::add-mask::${process.env[name]}`);'
setsid node --env-file=.env scripts/start.ts > "$work/application.log" 2>&1 &
supervisor=$!
ready=false
for attempt in {1..40}; do
  if ! kill -0 "$supervisor" 2>/dev/null; then
    echo 'CI application exited before readiness; raw service output is not published.' >&2
    exit 1
  fi
  if curl --fail --silent --max-time 2 http://127.0.0.1:3000/api/health > "$work/health.json" \
    && node --input-type=module - "$work/health.json" <<'JS'
import { readFileSync } from 'node:fs';
const health = JSON.parse(readFileSync(process.argv[2], 'utf8'));
if (health.status !== 'ok' || health.voice !== 'ready') process.exit(1);
JS
  then
    ready=true
    break
  fi
  sleep 0.5
done
if [[ $ready != true ]]; then
  echo 'CI web/control readiness timed out; media suite was not started.' >&2
  exit 1
fi
npm run test:e2e
echo 'Source checks and synthetic browser/media verification passed.'

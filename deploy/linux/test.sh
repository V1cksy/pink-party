#!/usr/bin/env bash
set -euo pipefail
umask 077
if [[ $(id -u) != 0 || $(uname -m) != aarch64 ]]; then
  echo 'Run with sudo inside the deployed Linux VM.' >&2
  exit 1
fi
export PATH=/opt/pink-party/node/bin:/opt/pink-party/bin:/usr/sbin:/usr/bin:/sbin:/bin
export DEBIAN_FRONTEND=noninteractive
apt-get install -y --no-install-recommends lsof
work=/var/tmp/pink-party-tests
rm -rf "$work"
install -d -m 0700 "$work"
tar -C /opt/pink-party/app --exclude=node_modules --exclude=.local -cf - . | tar -C "$work" -xf -
ln -s /opt/pink-party/app/node_modules "$work/node_modules"
ln -s /etc/pink-party/pink-party.env "$work/.env"
cd "$work"
npx playwright install --with-deps chromium
npm run check
PLAYWRIGHT_JSON_OUTPUT_FILE="$work/.local/browser-results.json" npm run test:e2e -- --reporter=line,json

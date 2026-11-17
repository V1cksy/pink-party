#!/usr/bin/env bash
set -euo pipefail
umask 077
if [[ $(id -u) != 0 || $(uname -m) != aarch64 ]]; then
  echo 'Run with sudo inside the healthy recovered ARM64 Ubuntu VM.' >&2
  exit 1
fi
app=/opt/pink-party/app
node=/opt/pink-party/node/bin/node
"$node" "$app/deploy/linux/service-health.ts"
pid=$(systemctl show pink-party.service --property=MainPID --value)
before_env=$(sha256sum /etc/pink-party/pink-party.env)
before_session=$(sha256sum "$app/data/session.json")
work=$(mktemp -d /var/tmp/pink-party-recovery-rejection.XXXXXX)
trap 'rm -rf "$work"' EXIT
if bash "$app/deploy/linux/install.sh" "$app" --recover-from "$work/missing" > "$work/rejected.log" 2>&1; then
  echo 'Recovery installer incorrectly accepted an existing deployment.' >&2
  exit 1
fi
grep -q '^Recovery inputs rejected;' "$work/rejected.log"
test "$(systemctl show pink-party.service --property=MainPID --value)" = "$pid"
test "$(sha256sum /etc/pink-party/pink-party.env)" = "$before_env"
test "$(sha256sum "$app/data/session.json")" = "$before_session"
"$node" "$app/deploy/linux/service-health.ts"
echo 'Recovery over an existing deployment rejected; healthy process and both recovered files unchanged.'

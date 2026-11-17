#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "$0")/../.."
config="$PWD/.local/cloud/ssh.conf"
COPYFILE_DISABLE=1 bash deploy/linux/archive.sh "$PWD" "$PWD/.local/cloud/check-source.tar"
gzip -f .local/cloud/check-source.tar
scp -F "$config" .local/cloud/check-source.tar.gz pink-party-cloud:/tmp/pink-party-check-source.tar.gz
ssh -F "$config" pink-party-cloud bash -s <<'REMOTE'
set -euo pipefail
umask 077
work=$(mktemp -d /var/tmp/pink-party-cloud-check.XXXXXX)
trap 'rm -rf "$work" /tmp/pink-party-check-source.tar.gz' EXIT
tar --no-same-owner -xzf /tmp/pink-party-check-source.tar.gz -C "$work"
export PATH=/opt/pink-party/node/bin:/opt/pink-party/bin:/usr/bin:/bin
cd "$work"
# Separate dependencies let Vite write its cache without changing the root-owned deployment.
npm ci --no-audit --no-fund
npm run check
REMOTE

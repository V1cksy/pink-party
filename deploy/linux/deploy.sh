#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "$0")/../.."
command -v limactl >/dev/null
mkdir -p .local
chmod 0700 .local
# Copy only public project files. Host credentials and generated state stay on the Mac.
COPYFILE_DISABLE=1 bash deploy/linux/archive.sh "$PWD" "$PWD/.local/linux-source.tar"
gzip -f .local/linux-source.tar
limactl copy .local/linux-source.tar.gz pink-party:/tmp/pink-party-source.tar.gz
limactl shell --workdir=/tmp pink-party bash -c '
  set -euo pipefail
  staging=$(mktemp -d /tmp/pink-party-deploy.XXXXXX)
  trap '\''rm -rf "$staging" /tmp/pink-party-source.tar.gz'\'' EXIT
  tar --no-same-owner -xzf /tmp/pink-party-source.tar.gz -C "$staging"
  sudo bash "$staging/deploy/linux/install.sh" "$staging"
'

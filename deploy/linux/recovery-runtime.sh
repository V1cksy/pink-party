#!/usr/bin/env bash
set -euo pipefail
umask 077
if [[ $(id -u) != 0 || $(uname -m) != aarch64 ]]; then
  echo 'Run with sudo inside the fresh ARM64 Ubuntu recovery VM.' >&2
  exit 1
fi
. /etc/os-release
if [[ $ID != ubuntu || $VERSION_ID != 24.04 ]]; then
  echo 'Recovery bootstrap supports Ubuntu 24.04 only.' >&2
  exit 1
fi
. "$(dirname "$0")/runtimes.sh"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends ca-certificates curl xz-utils libatomic1 python3 age
tools=/var/lib/pink-party-recovery-tools
install -d -o root -g root -m 0700 "$tools"
exec 9> "$tools/.lock"
flock -n 9 || { echo 'Another recovery bootstrap is running.' >&2; exit 1; }
fetch_runtime "$NODE_URL" "$tools/node.tar.xz" "$NODE_SHA256"
stage=$(mktemp -d "$tools/.node.XXXXXX")
trap 'rm -rf "$stage"' EXIT
tar -xJf "$tools/node.tar.xz" --strip-components=1 -C "$stage"
test "$("$stage/bin/node" --version)" = v24.22.2
if [[ -e $tools/node ]]; then
  if diff -qr "$stage" "$tools/node" >/dev/null; then
    echo 'Existing recovery validator runtime matches the pinned download.'
    exit 0
  fi
  echo 'Existing recovery runtime differs; inspect it before replacement.' >&2
  exit 1
fi
mv "$stage" "$tools/node"
echo 'Recovery validator runtime ready. Add /var/lib/pink-party-recovery-tools/node/bin to PATH.'

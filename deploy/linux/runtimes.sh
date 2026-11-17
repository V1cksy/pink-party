#!/usr/bin/env bash
# Shared pinned inputs for installation and recovery bootstrap.
NODE_URL=https://nodejs.org/dist/v24.22.2/node-v24.22.2-linux-arm64.tar.xz
NODE_SHA256=eb187837a2230d4047161ac0be008584e16b46f726e9c9490ee35dc6b17d9ba8
LIVEKIT_URL=https://github.com/livekit/livekit/releases/download/v1.13.11/livekit_1.13.11_linux_arm64.tar.gz
LIVEKIT_SHA256=2af6ce091d6b3c79d1677f8ff1bbb91a8007f40b2325c059b52d38383c0830b6

fetch_runtime() {
  local url=$1 target=$2 digest=$3 temporary
  if [[ -f $target ]] && echo "$digest  $target" | sha256sum -c --status; then
    return
  fi
  temporary=$(mktemp "${target}.pending.XXXXXX")
  if curl --fail --location --connect-timeout 15 --max-time 180 --max-filesize 134217728 "$url" -o "$temporary" \
    && echo "$digest  $temporary" | sha256sum -c --status; then
    mv "$temporary" "$target"
  else
    rm -f "$temporary"
    echo 'Pinned runtime download or checksum verification failed.' >&2
    return 1
  fi
}

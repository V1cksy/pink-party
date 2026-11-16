#!/usr/bin/env bash
set -euo pipefail
umask 077

if [[ $(id -u) != 0 || $(uname -m) != aarch64 ]]; then
  echo 'Run with sudo inside an ARM64 Ubuntu 24.04 VM.' >&2
  exit 1
fi
. /etc/os-release
if [[ $ID != ubuntu || $VERSION_ID != 24.04 ]]; then
  echo 'This installer is verified for Ubuntu 24.04 only.' >&2
  exit 1
fi
source_dir=$(cd "${1:?Pass the unpacked project directory}" && pwd)
test -f "$source_dir/server/index.ts"
test -f "$source_dir/deploy/linux/pink-party.service"
if [[ $source_dir == /opt/pink-party/app ]]; then
  echo 'Use a separate source checkout for deployment.' >&2
  exit 1
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y --no-install-recommends ca-certificates curl xz-utils libatomic1
install -d -m 0755 /opt/pink-party
install -d -m 0700 /var/cache/pink-party

fetch() {
  local url=$1 name=$2 digest=$3
  if [[ ! -f /var/cache/pink-party/$name ]] || ! echo "$digest  /var/cache/pink-party/$name" | sha256sum -c --status; then
    curl --fail --location --connect-timeout 15 --max-time 180 \
      "$url" -o "/var/cache/pink-party/$name"
    echo "$digest  /var/cache/pink-party/$name" | sha256sum -c --status
  fi
}
fetch 'https://nodejs.org/dist/v24.22.2/node-v24.22.2-linux-arm64.tar.xz' \
  node.tar.xz eb187837a2230d4047161ac0be008584e16b46f726e9c9490ee35dc6b17d9ba8
fetch 'https://github.com/livekit/livekit/releases/download/v1.13.11/livekit_1.13.11_linux_arm64.tar.gz' \
  livekit.tar.gz 2af6ce091d6b3c79d1677f8ff1bbb91a8007f40b2325c059b52d38383c0830b6
build_dir=$(mktemp -d /opt/pink-party/build.XXXXXX)
monitor_paused=false
cleanup() {
  local result=$?
  rm -rf "$build_dir"
  if [[ $monitor_paused == true ]]; then
    systemctl daemon-reload || result=1
    if ! systemctl enable --now pink-party-monitor.timer; then
      echo 'Monitoring could not resume; inspect pink-party-monitor.timer.' >&2
      result=1
    fi
  fi
  exit "$result"
}
trap cleanup EXIT
install -d -m 0755 "$build_dir/node" "$build_dir/bin" "$build_dir/app"
tar -xJf /var/cache/pink-party/node.tar.xz --strip-components=1 -C "$build_dir/node"
tar -xzf /var/cache/pink-party/livekit.tar.gz -C "$build_dir/bin" livekit-server
chmod -R u=rwX,go=rX "$build_dir/node" "$build_dir/bin"
export PATH="$build_dir/node/bin:$build_dir/bin:/usr/sbin:/usr/bin:/sbin:/bin"

if ! id pink-party >/dev/null 2>&1; then
  useradd --system --user-group --home-dir /var/lib/pink-party \
    --shell /usr/sbin/nologin pink-party
fi
if [[ $(id -u pink-party) == 0 || $(getent passwd pink-party | cut -d: -f7) != /usr/sbin/nologin ]]; then
  echo 'Existing pink-party account is unsuitable; inspect it before continuing.' >&2
  exit 1
fi
install -d -o pink-party -g pink-party -m 0700 /var/lib/pink-party
install -d -o root -g root -m 0700 /etc/pink-party
if [[ ! -e /etc/pink-party/pink-party.env ]]; then
  node --input-type=module -e '
    import { randomBytes } from "node:crypto";
    import { writeFileSync } from "node:fs";
    const fields = { PINK_PARTY_MODE: "local", JOIN_CODE: randomBytes(12).toString("hex"),
      LIVEKIT_API_KEY: randomBytes(12).toString("hex"), LIVEKIT_API_SECRET: randomBytes(32).toString("hex") };
    writeFileSync("/etc/pink-party/pink-party.env", Object.entries(fields).map(([k,v]) => `${k}=${v}\n`).join(""), { mode: 0o600, flag: "wx" });'
fi
chown root:root /etc/pink-party/pink-party.env
chmod 0600 /etc/pink-party/pink-party.env

bash "$source_dir/deploy/linux/archive.sh" "$source_dir" "$build_dir/source.tar"
tar --no-same-owner -C "$build_dir/app" -xf "$build_dir/source.tar"
cd "$build_dir/app"
npm ci --no-audit --no-fund
npm run build
chown -R root:root "$build_dir/app"
chmod -R u=rwX,go=rX "$build_dir/app"
ln -s /var/lib/pink-party .local

# Keep the running version available until its replacement has built successfully.
# Avoid running a check while its runtime/code is being replaced.
if systemctl cat pink-party-monitor.timer >/dev/null 2>&1; then
  monitor_paused=true
  systemctl stop pink-party-monitor.timer pink-party-monitor.service
fi
if systemctl cat pink-party.service >/dev/null 2>&1; then
  systemctl stop pink-party.service
fi
rm -rf /opt/pink-party/previous
install -d -m 0755 /opt/pink-party/previous
for unit in pink-party.service pink-party-monitor.service pink-party-monitor.timer; do
  if [[ -f /etc/systemd/system/$unit ]]; then
    cp "/etc/systemd/system/$unit" /opt/pink-party/previous/
  fi
done
if [[ -f /etc/systemd/journald@pink-party-monitor.conf.d/limits.conf ]]; then
  cp /etc/systemd/journald@pink-party-monitor.conf.d/limits.conf /opt/pink-party/previous/journald-monitor.conf
fi
for component in app node bin; do
  if [[ -e /opt/pink-party/$component ]]; then
    mv "/opt/pink-party/$component" /opt/pink-party/previous/
  fi
  mv "$build_dir/$component" "/opt/pink-party/$component"
done
cd /opt/pink-party/app
for unit in pink-party.service pink-party-monitor.service pink-party-monitor.timer; do
  install -o root -g root -m 0644 "deploy/linux/$unit" "/etc/systemd/system/$unit"
done
install -d -m 0755 /etc/systemd/journald@pink-party-monitor.conf.d
install -o root -g root -m 0644 deploy/linux/journald-monitor.conf \
  /etc/systemd/journald@pink-party-monitor.conf.d/limits.conf
systemd-analyze verify /etc/systemd/system/pink-party.service \
  /etc/systemd/system/pink-party-monitor.service /etc/systemd/system/pink-party-monitor.timer
systemctl daemon-reload
systemctl try-restart systemd-journald@pink-party-monitor.service
systemctl enable --now pink-party-monitor.timer
monitor_paused=false
systemctl reset-failed pink-party.service
systemctl enable --now pink-party.service
for attempt in {1..30}; do
  if /opt/pink-party/node/bin/node /opt/pink-party/app/deploy/linux/service-health.ts; then
    echo 'Linux deployment ready. Run the verification described in docs/linux-deployment.md.'
    exit 0
  fi
  sleep 1
done
echo 'Startup failed. Inspect sudo journalctl -u pink-party.service.' >&2
exit 1

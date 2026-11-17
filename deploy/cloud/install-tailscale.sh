#!/usr/bin/env bash
set -euo pipefail
umask 077
[[ $(id -u) == 0 && $(uname -m) == aarch64 ]]
. /etc/os-release
[[ $ID == ubuntu && $VERSION_ID == 24.04 ]]
if command -v tailscale >/dev/null || systemctl cat tailscaled.service >/dev/null 2>&1; then
  echo 'An existing Tailscale installation was preserved; inspect it before proceeding.' >&2
  exit 1
fi
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
curl --fail --location --connect-timeout 15 --max-time 180 \
  https://pkgs.tailscale.com/stable/tailscale_1.104.7_arm64.tgz -o "$work/tailscale.tgz"
echo "d6bed2720310b328b861f943d7b4016c5358a9bad60575eb51e8143b79068484  $work/tailscale.tgz" | sha256sum -c --status
tar -xzf "$work/tailscale.tgz" -C "$work"
install -m 0755 "$work/tailscale_1.104.7_arm64/tailscale" /usr/bin/tailscale
install -m 0755 "$work/tailscale_1.104.7_arm64/tailscaled" /usr/sbin/tailscaled
install -m 0644 "$work/tailscale_1.104.7_arm64/systemd/tailscaled.service" /etc/systemd/system/tailscaled.service
install -m 0644 "$work/tailscale_1.104.7_arm64/systemd/tailscaled.defaults" /etc/default/tailscaled
systemctl daemon-reload
systemctl enable --now tailscaled.service
echo 'Installed pinned Linux Tailscale. Sign in separately on this host; Mac state and keys were not transferred.'

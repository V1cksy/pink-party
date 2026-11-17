#!/usr/bin/env bash
set -euo pipefail
umask 077
cd "$(dirname "$0")/../.."
config="$PWD/.local/cloud/ssh.conf"
[[ -f $config && -f .local/cloud/known_hosts ]]
# The separate SSH config must use the lab key and a console-verified host key.
options=(-F "$config" -o BatchMode=yes -o StrictHostKeyChecking=yes -o "UserKnownHostsFile=$PWD/.local/cloud/known_hosts")
COPYFILE_DISABLE=1 bash deploy/linux/archive.sh "$PWD" "$PWD/.local/cloud/source.tar"
gzip -f .local/cloud/source.tar
shasum -a 256 .local/cloud/source.tar.gz | awk '{print $1}' > .local/cloud/source.sha256
scp "${options[@]}" .local/cloud/source.tar.gz .local/cloud/source.sha256 pink-party-cloud:/tmp/
ssh "${options[@]}" pink-party-cloud bash -s <<'REMOTE'
set -euo pipefail
umask 077
work=$(mktemp -d)
trap 'rm -rf "$work" /tmp/source.tar.gz /tmp/source.sha256' EXIT
printf '%s  /tmp/source.tar.gz\n' "$(cat /tmp/source.sha256)" | sha256sum -c --status
tar --no-same-owner -xzf /tmp/source.tar.gz -C "$work"
sudo bash "$work/deploy/linux/install.sh" "$work"
REMOTE

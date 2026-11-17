#!/usr/bin/env bash
set -euo pipefail
umask 077
source_dir=$(cd "${1:?Pass the reviewed public source directory}" && pwd)
encrypted=${2:?Pass the encrypted snapshot path}
identity=${3:?Pass the recovery identity path}
if [[ $# != 3 || $(id -u) != 0 ]]; then
  echo 'Usage: sudo bash recovery-install.sh SOURCE ENCRYPTED_SNAPSHOT RECOVERY_IDENTITY' >&2
  exit 1
fi
python3 -B "$source_dir/deploy/linux/recovery-config.py" check-fresh
bash "$source_dir/deploy/linux/recovery-runtime.sh"
export PATH=/var/lib/pink-party-recovery-tools/node/bin:/usr/sbin:/usr/bin:/sbin:/bin
install -d -o root -g root -m 0700 /var/lib/pink-party-restores
work=$(mktemp -d /var/lib/pink-party-restores/rebuild.XXXXXX)
trap 'rm -rf "$work"' EXIT
python3 -B "$source_dir/deploy/linux/encrypted-backup.py" restore "$encrypted" "$work/recovered" \
  --identity-file "$identity" --work-dir "$work"
bash "$source_dir/deploy/linux/install.sh" "$source_dir" --recover-from "$work/recovered"

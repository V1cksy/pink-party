#!/usr/bin/env bash
set -euo pipefail
umask 077
source_dir=$(cd "${1:?Pass the project directory}" && pwd)
archive=${2:?Pass an absolute output tar path}
if [[ $archive != /* ]]; then
  echo 'The output archive path must be absolute.' >&2
  exit 1
fi
tar -C "$source_dir" --exclude=node_modules --exclude=.local \
  --exclude=.env --exclude='.env.*' \
  -cf "$archive" -T "$source_dir/deploy/linux/files.txt"
# These two public templates are the only environment files included.
tar -C "$source_dir" -rf "$archive" .env.example .env.private.example

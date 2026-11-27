#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
umask 077
mkdir -p backups
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
target="backups/clipfactory-${stamp}.tar.gz"
# Stop all writers for a consistent database and media snapshot.
docker compose -f compose.business.yaml stop factory
trap 'docker compose -f compose.business.yaml up -d factory' EXIT
sudo tar --numeric-owner -czf "$target.partial" -C data .
sudo chown "$(id -u):$(id -g)" "$target.partial"
chmod 600 "$target.partial"
mv "$target.partial" "$target"
sha256sum "$target" > "$target.sha256"
printf 'Backup: %s\n' "$target"

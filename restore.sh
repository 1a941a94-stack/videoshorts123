#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
umask 077
archive="${1:?Usage: bash restore.sh backups/clipfactory-DATE.tar.gz}"
[[ -f "$archive" && -f "$archive.sha256" ]] || { echo "Archive or checksum missing"; exit 1; }
sha256sum -c "$archive.sha256"
# Restore only trusted archives created by backup.sh.
read -r -p "Stop factory and restore trusted archive? Type RESTORE: " confirm
[[ "$confirm" == RESTORE ]] || exit 1
staging="$(mktemp -d ./restore-staging.XXXXXX)"
sudo tar --no-same-owner -xzf "$archive" -C "$staging"
sudo chown -R 10001:10001 "$staging"
docker compose -f compose.business.yaml stop factory
old="data-before-restore-$(date -u +%Y%m%dT%H%M%SZ)"
if [[ -e data ]]; then mv data "$old"; fi
mv "$staging" data
docker compose -f compose.business.yaml up -d factory
printf 'Previous data retained: %s\n' "$old"

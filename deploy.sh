#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
umask 077
docker compose version >/dev/null
if [[ ! -f .env ]]; then cp .env.example .env; chmod 600 .env; fi
mkdir -p data backups
if [[ "$(stat -c %u data)" != 10001 ]]; then sudo chown -R 10001:10001 data; fi
docker compose -f compose.business.yaml config --quiet
docker compose -f compose.business.yaml up -d --build
docker compose -f compose.business.yaml ps

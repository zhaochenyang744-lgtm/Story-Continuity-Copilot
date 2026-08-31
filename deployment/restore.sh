#!/usr/bin/env bash
set -euo pipefail

bundle_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
environment_file=${1:-$bundle_root/deploy.env}
release_id=${2:-}
backup_name=${3:-}
backup_sha256=${4:-}
if [[ -z "$release_id" || -z "$backup_name" || ! "$backup_sha256" =~ ^[0-9A-Fa-f]{64}$ || ! -f "$environment_file" ]]; then
  exit 64
fi

cd "$bundle_root"
export RELEASE_ID="$release_id"
set -a
source "$environment_file"
set +a
bash "$bundle_root/deployment/secret-dir-check.sh" "${SCC_SECRET_DIR:-}"
compose=(docker compose --env-file "$environment_file" -f deployment/compose.yaml)
"${compose[@]}" stop caddy frontend backend
"${compose[@]}" run --rm --no-deps backend python -m app.deployment restore \
  --backup-dir /backups \
  --backup-name "$backup_name" \
  --sha256 "$backup_sha256" \
  --offline-confirmation APPLICATION_STOPPED
"${compose[@]}" up -d --no-build --remove-orphans

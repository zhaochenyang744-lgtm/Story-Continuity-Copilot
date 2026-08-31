#!/usr/bin/env bash
set -euo pipefail

bundle_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
environment_file=${1:-$bundle_root/deploy.env}
release_id=${2:-}
if [[ -z "$release_id" || ! "$release_id" =~ ^[a-zA-Z0-9._-]{7,80}$ || ! -f "$environment_file" ]]; then
  exit 64
fi

cd "$bundle_root"
export RELEASE_ID="$release_id"
set -a
source "$environment_file"
set +a
bash "$bundle_root/deployment/secret-dir-check.sh" "${SCC_SECRET_DIR:-}"
compose=(docker compose --env-file "$environment_file" -f deployment/compose.yaml)
"${compose[@]}" config --quiet
if "${compose[@]}" ps --status running --services | grep -qx backend; then
  "${compose[@]}" exec -T backend python -m app.deployment backup --backup-dir /backups --label "pre-release-$release_id"
fi
"${compose[@]}" build --pull=false backend frontend
bash "$bundle_root/deployment/verify-frontend-image.sh" "localhost/story-continuity-frontend:$release_id"
"${compose[@]}" up -d --no-build --remove-orphans

for _ in $(seq 1 30); do
  if curl --fail --silent --show-error --max-time 5 "https://$PUBLIC_HOST/readiness" >/dev/null; then
    install -d -m 0700 "$bundle_root/release-state"
    if [[ -f "$bundle_root/release-state/current" ]]; then
      cp -- "$bundle_root/release-state/current" "$bundle_root/release-state/previous"
    fi
    printf '%s\n' "$release_id" > "$bundle_root/release-state/current"
    exit 0
  fi
  sleep 2
done
exit 70

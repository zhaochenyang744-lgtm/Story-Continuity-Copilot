#!/usr/bin/env bash
set -euo pipefail

bundle_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
environment_file=${1:-$bundle_root/deploy.env}
target_release=${2:-}
if [[ -z "$target_release" || ! "$target_release" =~ ^[a-zA-Z0-9._-]{7,80}$ || ! -f "$environment_file" ]]; then
  exit 64
fi
if ! docker image inspect "localhost/story-continuity-backend:$target_release" >/dev/null 2>&1 \
  || ! docker image inspect "localhost/story-continuity-frontend:$target_release" >/dev/null 2>&1; then
  exit 66
fi

cd "$bundle_root"
export RELEASE_ID="$target_release"
set -a
source "$environment_file"
set +a
bash "$bundle_root/deployment/secret-dir-check.sh" "${SCC_SECRET_DIR:-}"
bash "$bundle_root/deployment/verify-frontend-image.sh" "localhost/story-continuity-frontend:$target_release"
compose=(docker compose --env-file "$environment_file" -f deployment/compose.yaml)
if "${compose[@]}" ps --status running --services | grep -qx backend; then
  "${compose[@]}" exec -T backend python -m app.deployment backup --backup-dir /backups --label "pre-rollback-$target_release"
fi
"${compose[@]}" up -d --no-build --remove-orphans

for _ in $(seq 1 30); do
  if curl --fail --silent --show-error --max-time 5 "https://$PUBLIC_HOST/readiness" >/dev/null; then
    exit 0
  fi
  sleep 2
done
exit 70

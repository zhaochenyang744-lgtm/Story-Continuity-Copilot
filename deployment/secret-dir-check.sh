#!/usr/bin/env bash
set -euo pipefail

secret_dir=${1:-}
if [[ -z "$secret_dir" || "$secret_dir" != /* || ! -d "$secret_dir" || -L "$secret_dir" ]]; then
  exit 64
fi

if [[ "$(stat -c '%u' -- "$secret_dir")" != "0" || "$(stat -c '%g' -- "$secret_dir")" != "0" || "$(stat -c '%a' -- "$secret_dir")" != "700" ]]; then
  exit 77
fi

secret_names=(CONTINUITY_API_KEY SMTP_USERNAME SMTP_PASSWORD SMTP_FROM RECOVERY_HASH_SECRET)
for secret_name in "${secret_names[@]}"; do
  secret_path="$secret_dir/$secret_name"
  if [[ ! -f "$secret_path" || -L "$secret_path" || ! -s "$secret_path" ]]; then
    exit 78
  fi
  if [[ "$(stat -c '%u' -- "$secret_path")" != "0" || "$(stat -c '%g' -- "$secret_path")" != "0" || "$(stat -c '%a' -- "$secret_path")" != "600" ]]; then
    exit 77
  fi
done

#!/bin/sh
set -eu

secret_names="CONTINUITY_API_KEY SMTP_USERNAME SMTP_PASSWORD SMTP_FROM RECOVERY_HASH_SECRET"
for secret_name in $secret_names; do
  secret_path="/run/secrets/$secret_name"
  if [ ! -s "$secret_path" ]; then
    exit 78
  fi
  secret_value=$(cat "$secret_path")
  export "$secret_name=$secret_value"
  unset secret_value
done

if [ "${1:-}" = "python" ] && [ "${2:-}" = "-m" ] && [ "${3:-}" = "uvicorn" ]; then
  gosu continuity python -m app.deployment migrate
fi

exec gosu continuity "$@"

#!/usr/bin/env bash
set -euo pipefail

image=${1:-}
if [[ ! "$image" =~ ^localhost/story-continuity-frontend:[a-zA-Z0-9._-]{7,80}$ ]]; then
  exit 64
fi

platform=$(docker image inspect --format '{{.Os}}/{{.Architecture}}' "$image")
if [[ "$platform" != "linux/amd64" ]]; then
  exit 65
fi

docker run --rm --entrypoint /bin/sh "$image" -ceu '
  test "$(node -p "process.platform + \"/\" + process.arch")" = "linux/x64"
  ldd --version 2>&1 | grep -qi musl
  if find /app -type f \( -iname "*win32*" -o -iname "*windows*" \) -print | grep -q .; then
    exit 66
  fi
  find /app -type f -name "*.node" -exec sh -ceu '\''
    for file do
      magic=$(od -An -tx1 -N4 "$file" | tr -d " \n")
      test "$magic" = "7f454c46"
    done
  '\'' sh {} +
  find /app -type f -path "*sharp-linuxmusl-x64*" -name "*.node" -print | grep -q .
  node -e "require(\"sharp\")"
'

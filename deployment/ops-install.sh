#!/usr/bin/env bash
# Run only after local acceptance and the operator has reviewed the concrete config.
set -euo pipefail
umask 077
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
config=${1:-}
mode=${2:---install-only}
if [[ $EUID != 0 || ! -f "$config" || ! "$mode" =~ ^--(install-only|enable)$ ]]; then
  echo 'Usage: sudo bash deployment/ops-install.sh /absolute/ops-config.json [--install-only|--enable]' >&2
  exit 64
fi
python3 - "$root/backend/app/operations.py" "$config" <<'PY'
import importlib.util, pathlib, sys
spec = importlib.util.spec_from_file_location('operations', sys.argv[1])
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
module.load_config(pathlib.Path(sys.argv[2]))
print('{"configuration_valid":true}')
PY
install -d -m 0700 /opt/story-continuity-ops /etc/story-continuity-ops
install -m 0600 "$root/backend/app/operations.py" /opt/story-continuity-ops/operations.py
install -m 0600 "$config" /etc/story-continuity-ops/config.json
install -m 0644 "$root"/deployment/systemd/story-continuity-ops* /etc/systemd/system/
systemctl daemon-reload
if [[ "$mode" == --enable ]]; then
  # Initial failed backup/monitor (e.g. no offsite target) remains observable; timers still start.
  systemctl enable --now story-continuity-ops-backup.timer story-continuity-ops-monitor.timer story-continuity-ops-drill.timer
  systemctl start story-continuity-ops@backup.service || true
  systemctl start story-continuity-ops@drill.service || true
  systemctl start story-continuity-ops@monitor.service || true
fi
systemctl list-timers 'story-continuity-ops*' --no-pager
echo '{"installed":true,"activation_must_be_verified_with_systemctl_and_state_files":true}'

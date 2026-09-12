"""Build a source-only, explicitly allowlisted operations installation archive."""
import hashlib
import json
from pathlib import Path
import zipfile

root = Path(__file__).resolve().parents[1]
output = root / "artifacts/current-stage-completion/operations"
output.mkdir(parents=True, exist_ok=True)
names = ["backend/app/operations.py", "deployment/ops-config.example.json", "deployment/ops-install.sh",
         "deployment/systemd/story-continuity-ops@.service", "deployment/systemd/story-continuity-ops-backup.timer",
         "deployment/systemd/story-continuity-ops-monitor.timer", "deployment/systemd/story-continuity-ops-drill.timer",
         "docs/operations.md"]
manifest = {"package_type": "operations_source_only", "production_activated": False,
            "files": {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in names}}
destination = output / "ops-installation-package.zip"
with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for name in names:
        archive.writestr(name, (root / name).read_bytes())
    archive.writestr("operations-package-manifest.json", json.dumps(manifest, sort_keys=True, indent=2))
with zipfile.ZipFile(destination) as archive:
    assert archive.testzip() is None
    assert set(archive.namelist()) == set(names) | {"operations-package-manifest.json"}
    for name, expected in manifest["files"].items():
        assert hashlib.sha256(archive.read(name)).hexdigest() == expected
result = {"package_name": destination.name, "file_count": len(names),
          "sha256": hashlib.sha256(destination.read_bytes()).hexdigest(), "verified": True,
          "contains_runtime_or_credentials": False, "production_activated": False,
          "linux_systemd_execution": "pending_target_host_validation", "bash_syntax_execution": "unavailable_on_local_windows_host"}
(output / "package.json").write_text(json.dumps(result, sort_keys=True, indent=2) + "\n", encoding="utf-8")
print(json.dumps(result))

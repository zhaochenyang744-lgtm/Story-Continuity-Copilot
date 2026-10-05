"""Execute the release shell in a temporary bundle with Docker/HTTP stubs."""
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


RELEASE = Path(__file__).resolve().parents[2] / "deployment" / "release.sh"


def bash_executable():
    candidates = [shutil.which("bash")]
    git = shutil.which("git")
    if git:
        candidates.append(str(Path(git).parent.parent / "usr" / "bin" / "sh.exe"))
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            result = subprocess.run([candidate, "--version"], capture_output=True, text=True, encoding="utf-8")
            if result.returncode == 0 and "GNU bash" in result.stdout:
                return candidate
    return None


class ReleaseScriptTests(unittest.TestCase):
    def test_explicit_release_controls_every_step_and_receipt_after_sourcing_env(self):
        shell = bash_executable()
        if not shell:
            self.skipTest("GNU Bash unavailable; this test never invokes real Docker or HTTP")
        for configured_release in ("RELEASE_ID=old-environment-release\n", ""):
            with self.subTest(env_release=bool(configured_release)), tempfile.TemporaryDirectory(prefix="release-priority-") as temporary:
                root = Path(temporary)
                (root / "release-state").mkdir()
                deployment = root / "deployment"
                deployment.mkdir()
                release = deployment / "release.sh"
                release.write_text(RELEASE.read_text(encoding="utf-8"), encoding="utf-8", newline="\n")
                environment_file = root / "deploy.env"
                environment_file.write_text("PUBLIC_HOST=local.test\n" + configured_release, encoding="utf-8", newline="\n")
                wrapper = root / "run-stub.sh"
                wrapper.write_text(r'''#!/usr/bin/env bash
set -euo pipefail
docker() {
  printf 'docker %s | release=%s\n' "$*" "${RELEASE_ID:-unset}" >> "$STUB_LOG"
  if [[ "$*" == *' ps '* ]]; then printf '%s\n' backend; fi
  return 0
}
bash() { printf 'helper %s | release=%s\n' "$*" "${RELEASE_ID:-unset}" >> "$STUB_LOG"; }
curl() { printf 'http %s | release=%s\n' "$*" "${RELEASE_ID:-unset}" >> "$STUB_LOG"; }
seq() { printf '%s\n' 1; }
install() { return 0; }
source "$1" "$2" "$3"
''', encoding="utf-8", newline="\n")
                log = root / "commands.log"
                environment = {**os.environ, "RELEASE_ID": "old-inherited-release", "STUB_LOG": log.as_posix(),
                               "PATH": str(Path(shell).parent) + os.pathsep + os.environ.get("PATH", "")}
                result = subprocess.run([shell, str(wrapper), str(release), str(environment_file), "explicit-new-release"],
                                        cwd=root, env=environment, capture_output=True, text=True, encoding="utf-8", timeout=20)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                lines = log.read_text(encoding="utf-8").splitlines()
                self.assertTrue(lines)
                for line in lines:
                    self.assertTrue(line.endswith(" | release=explicit-new-release"), line)
                joined = "\n".join(lines)
                self.assertIn("config --quiet", joined)
                self.assertIn("backup --backup-dir /backups --label pre-release-explicit-new-release", joined)
                self.assertIn("build --pull=false backend frontend", joined)
                self.assertIn("localhost/story-continuity-frontend:explicit-new-release", joined)
                self.assertIn("up -d --no-build --remove-orphans", joined)
                self.assertLess(joined.index("app.deployment backup"), joined.index("build --pull=false"))
                self.assertLess(joined.index("verify-frontend-image.sh"), joined.index("up -d"))
                self.assertEqual((root / "release-state" / "current").read_text(encoding="utf-8"), "explicit-new-release\n")
                self.assertEqual(environment_file.read_text(encoding="utf-8"), "PUBLIC_HOST=local.test\n" + configured_release)


if __name__ == "__main__":
    unittest.main()

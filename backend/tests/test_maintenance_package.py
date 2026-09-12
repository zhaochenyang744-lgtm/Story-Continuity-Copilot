"""Offline source package negative controls; no application import or real database."""
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest
from unittest.mock import patch


REPO = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("source_package", REPO / "deployment/build-maintenance-source.py")
package = importlib.util.module_from_spec(spec)
spec.loader.exec_module(package)


class SourcePackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scc-source-package-test-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = {"schema": "story-continuity-maintenance-source-v1", "candidate": "test-only",
                         "include": [{"source": "backend/app/main.py", "target": "backend/app/main.py"},
                                     {"source": "frontend/app/[[...path]]/page.tsx",
                                      "target": "frontend-source/app/[[...path]]/page.tsx"},
                                     {"source": "deployment/release.sh", "target": "deployment/release.sh"}],
                         "complete_trees": ["backend/app", "frontend/app"],
                         "required_targets": ["deployment/release.sh"]}
        for entry in self.manifest["include"]:
            self.write(entry["source"], b"safe source\n")
        self.save_manifest()

    def write(self, name, data):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def save_manifest(self):
        self.write(package.DEFAULT_MANIFEST, package.encoded(self.manifest))

    def plan(self):
        return package.make_plan(self.root)[0]

    def build(self, name="source.tar.gz"):
        return package.build_archive(self.root, package.DEFAULT_MANIFEST, self.root / name,
                                     self.plan()["inventory_sha256"])

    def test_reproducible_bytes_and_every_source_sha256_roundtrip(self):
        first, second = self.build(), self.build("second.tar.gz")
        self.assertEqual(first["archive_sha256"], second["archive_sha256"])
        self.assertEqual(first["file_count"], 3)
        self.assertTrue(package.verify_archive(self.root / "source.tar.gz")["verified"])
        with tarfile.open(self.root / "source.tar.gz") as archive:
            inventory = json.load(archive.extractfile(package.INVENTORY_NAME))
            for entry in inventory["files"]:
                self.assertEqual(archive.extractfile(entry["target"]).read(),
                                 (self.root / entry["source"]).read_bytes())

    def test_unlisted_secret_database_evidence_and_cache_are_never_read(self):
        for name in [".env", "runtime/user.db", "backend/evidence/private.txt", "frontend/AGENTS.md",
                     "frontend/app/__pycache__/a.pyc"]:
            self.write(name, b"must not leave this folder")
        original = Path.read_bytes
        def checked(path):
            self.assertNotIn(path.name, {".env", "user.db", "private.txt", "AGENTS.md", "a.pyc"})
            return original(path)
        with patch.object(Path, "read_bytes", checked):
            self.build()

    def test_explicit_protected_paths_and_traversal_are_rejected(self):
        for value in [".env", "backend/../outside.py", "backend/app/a:secret", "/absolute", "CON.py",
                      "backend/app/user.sqlite3", "backend/tests/fixture.py", "AGENTS.md"]:
            with self.subTest(value=value):
                self.manifest["include"][0]["source"] = value
                self.save_manifest()
                with self.assertRaises(package.PackageError):
                    self.plan()

    def test_destination_collision_rejected_case_insensitively(self):
        self.manifest["include"][1]["target"] = "BACKEND/app/main.py"
        self.save_manifest()
        with self.assertRaisesRegex(package.PackageError, "colliding"):
            self.plan()

    def test_new_source_file_cannot_silently_be_omitted(self):
        self.write("backend/app/new_workflow.py", b"new module")
        with self.assertRaisesRegex(package.PackageError, "missing from explicit"):
            self.plan()

    def test_missing_required_deployment_contract_file_rejected(self):
        self.manifest["include"].pop()
        self.save_manifest()
        with self.assertRaisesRegex(package.PackageError, "required"):
            self.plan()

    def test_credential_database_executable_and_crlf_controls(self):
        for data in [b"sk-" + b"a" * 30, b"-----BEGIN RSA PRIVATE KEY-----",
                     b"SQLite format 3\x00", b"MZbinary", b"#token=" + b"x" * 40,
                     b"C:\\Users\\someone\\private.txt"]:
            with self.subTest(signature=data[:8]):
                self.write("backend/app/main.py", data)
                with self.assertRaises(package.PackageError):
                    self.plan()
        self.write("backend/app/main.py", b"source\n")
        self.write("deployment/release.sh", b"#!/bin/bash\r\n")
        with self.assertRaisesRegex(package.PackageError, "LF"):
            self.plan()

    def test_source_drift_after_plan_and_during_build_rejected_without_output(self):
        inventory = self.plan()
        self.write("backend/app/main.py", b"edited")
        with self.assertRaisesRegex(package.PackageError, "changed since"):
            package.build_archive(self.root, package.DEFAULT_MANIFEST, self.root / "never.tar.gz",
                                  inventory["inventory_sha256"])
        original = package.make_plan
        calls = 0
        def mutate(*args, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 2:
                self.write("backend/app/main.py", b"edited during archive")
            return original(*args, **kwargs)
        current = self.plan()
        with patch.object(package, "make_plan", mutate):
            with self.assertRaisesRegex(package.PackageError, "while building"):
                package.build_archive(self.root, package.DEFAULT_MANIFEST, self.root / "never.tar.gz",
                                      current["inventory_sha256"])
        self.assertFalse((self.root / "never.tar.gz").exists())

    def test_symlink_ancestor_rejected(self):
        real = self.root / "external"
        real.mkdir()
        (real / "a.py").write_text("source")
        linked = self.root / "linked"
        try:
            linked.symlink_to(real, target_is_directory=True)
        except OSError as error:
            if os.name != "nt":
                self.skipTest(f"host cannot create directory symlink: {error}")
            # Junction creation requires no Windows developer mode. Both resolved
            # paths are within this test's unique managed temporary directory.
            self.assertTrue(real.resolve().is_relative_to(self.root.resolve()))
            self.assertTrue(linked.parent.resolve().is_relative_to(self.root.resolve()))
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 "New-Item -ItemType Junction -Path $env:SCC_TEST_LINK -Target $env:SCC_TEST_TARGET | Out-Null"],
                env={**os.environ, "SCC_TEST_LINK": str(linked), "SCC_TEST_TARGET": str(real)},
                check=True, capture_output=True, creationflags=subprocess.CREATE_NO_WINDOW,
            )
        self.manifest["include"][0]["source"] = "linked/a.py"
        self.save_manifest()
        with self.assertRaisesRegex(package.PackageError, "links"):
            self.plan()

    def test_archive_tampering_and_foreign_inventory_rejected(self):
        self.build()
        source = self.root / "source.tar.gz"
        with tarfile.open(source) as archive:
            members = [(member, archive.extractfile(member).read()) for member in archive]
        for name, extra in [("bytes", False), ("extra", True)]:
            path = self.root / (name + ".tar.gz")
            with tarfile.open(path, "w:gz") as archive:
                for member, data in members:
                    if not extra and member.name == "backend/app/main.py":
                        data = b"tampered"
                        member.size = len(data)
                    archive.addfile(member, io.BytesIO(data))
                if extra:
                    member = tarfile.TarInfo("../escape")
                    member.size = 3
                    archive.addfile(member, io.BytesIO(b"bad"))
            with self.assertRaises(package.PackageError):
                package.verify_archive(path)
        with self.assertRaisesRegex(package.PackageError, "approved inventory"):
            package.verify_archive(source, "0" * 64)
        with self.assertRaisesRegex(package.PackageError, "refusing overwrite"):
            self.build()


if __name__ == "__main__":
    unittest.main()

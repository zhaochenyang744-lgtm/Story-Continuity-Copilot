"""Offline deterministic source packaging. No deployment, provider or credential loading."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile


DEFAULT_MANIFEST = "docs/maintenance-release-manifest.json"
INVENTORY_NAME = "SOURCE-PACKAGE.json"
MAX_FILE_BYTES = 32 * 1024 * 1024
MAX_TOTAL_BYTES = 128 * 1024 * 1024
FORBIDDEN_PARTS = {
    ".git", ".next", "node_modules", "__pycache__", "runtime", "evidence",
    "artifacts", "evaluation", "test-results", "playwright-report", "screenshots",
    "secrets", "secret", ".ssh", ".aws", ".codex", "tests", "e2e",
}
SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN (?:[A-Z ]+ )?PRIVATE KEY-----"),
    re.compile(rb"(?<![A-Za-z0-9])sk-[A-Za-z0-9_-]{20,}"),
    re.compile(rb"AKIA[0-9A-Z]{16}"),
    re.compile(rb"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(rb'(?i)(?:api[_-]?key|smtp_password|recovery_hash_secret|access_token)'
               rb'\s*[=:]\s*["\x27][A-Za-z0-9_+/.=-]{24,}["\x27]'),
)


class PackageError(ValueError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def encoded(value) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def safe_name(value: str) -> str:
    if (not isinstance(value, str) or not value or "\\" in value or
            any(ord(c) < 32 for c in value) or any(c in value for c in ':*?"<>|') or
            value.startswith("/") or any(p in ("", ".", "..") for p in value.split("/"))):
        raise PackageError("invalid normalized relative path")
    for part in value.split("/"):
        if part.endswith((" ", ".")) or re.fullmatch(r"(?i)(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\..*)?", part):
            raise PackageError("unsafe portable filename")
    return value


def protected(value: str) -> bool:
    parts = PurePosixPath(value).parts
    low = [p.casefold() for p in parts]
    name = low[-1]
    return (any(p in FORBIDDEN_PARTS or p.startswith(".env") or p.startswith(".next") for p in low)
            or name in {"agents.md", "claude.md", "trace.zip", "deploy.env", ".last-run.json"}
            or re.search(r"\.(?:db|sqlite\d*|pem|p12|pfx|key)(?:-(?:wal|shm))?$", name) is not None
            or name.endswith((".pyc", ".tsbuildinfo", ".exe", ".dll", ".node", ".so", ".dylib", ".pdb"))
            or name.startswith(("test-failed-", "devdiag-")))


def is_link(path: Path) -> bool:
    # is_junction was introduced in Python 3.12. Linux Python 3.10 still
    # rejects symlinks; on Windows 3.10 detect reparse points via lstat.
    junction = getattr(path, "is_junction", lambda: False)()
    reparse = bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400) if path.exists() else False
    return path.is_symlink() or junction or reparse


def safe_file(root: Path, name: str) -> Path:
    safe_name(name)
    target = root
    for part in name.split("/"):
        target = target / part
        if is_link(target):
            raise PackageError(f"links are forbidden: {name}")
    if not target.is_file() or not target.resolve().is_relative_to(root):
        raise PackageError(f"missing or non-regular file: {name}")
    if not stat.S_ISREG(target.stat().st_mode):
        raise PackageError(f"special file forbidden: {name}")
    return target


def scan_bytes(name: str, data: bytes) -> None:
    if len(data) > MAX_FILE_BYTES:
        raise PackageError(f"file size limit: {name}")
    if any(pattern.search(data) for pattern in SECRET_PATTERNS):
        raise PackageError(f"credential signature detected (value withheld): {name}")
    if data.startswith(b"SQLite format 3\x00"):
        raise PackageError(f"database signature detected: {name}")
    if data.startswith((b"MZ", b"\x7fELF", b"\xfe\xed\xfa\xce", b"\xfe\xed\xfa\xcf",
                        b"\xce\xfa\xed\xfe", b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe")):
        raise PackageError(f"prebuilt executable signature detected: {name}")
    if re.search(rb"[A-Za-z]:\\(?:Users|Documents)\\|/(?:Users|home)/[^/\s]+/", data):
        raise PackageError(f"private absolute path detected: {name}")
    if re.search(rb"#token=[A-Za-z0-9_-]{32,}", data):
        raise PackageError(f"embedded reset token detected: {name}")
    if name.endswith((".sh", ".service", ".timer")) and b"\r" in data:
        raise PackageError(f"Linux executable/config must use LF: {name}")


def load_manifest(root: Path, relative: str) -> dict:
    manifest = json.loads(safe_file(root, relative).read_text(encoding="utf-8"))
    if manifest.get("schema") != "story-continuity-maintenance-source-v1":
        raise PackageError("unsupported manifest schema")
    if not isinstance(manifest.get("include"), list) or not manifest["include"]:
        raise PackageError("empty explicit include manifest")
    return manifest


def make_plan(root: Path, manifest_path: str = DEFAULT_MANIFEST) -> tuple[dict, dict[str, bytes]]:
    root = root.resolve(strict=True)
    manifest = load_manifest(root, manifest_path)
    payload: dict[str, bytes] = {}
    entries, sources, destinations = [], set(), set()
    total = 0
    for entry in manifest["include"]:
        if not isinstance(entry, dict) or set(entry) != {"source", "target"}:
            raise PackageError("include entries need exactly source and target")
        source, target = safe_name(entry["source"]), safe_name(entry["target"])
        if protected(source) or protected(target) or target.casefold() == INVENTORY_NAME.casefold():
            raise PackageError(f"protected package path: {source}")
        if source.casefold() in sources or target.casefold() in destinations:
            raise PackageError("duplicate or case-colliding source/target")
        sources.add(source.casefold())
        destinations.add(target.casefold())
        file_path = safe_file(root, source)
        if file_path.stat().st_size > MAX_FILE_BYTES:
            raise PackageError(f"file size limit: {source}")
        data = file_path.read_bytes()
        scan_bytes(source, data)
        total += len(data)
        if total > MAX_TOTAL_BYTES:
            raise PackageError("package size limit")
        payload[target] = data
        entries.append({"source": source, "target": target, "bytes": len(data),
                        "sha256": digest(data), "mode": "0755" if target.endswith(".sh") else "0644"})
    for required in manifest.get("required_targets", []):
        if safe_name(required) not in payload:
            raise PackageError(f"missing required build/deployment target: {required}")
    # Enumerate names only; protected files are never opened or exported.
    for tree in manifest.get("complete_trees", []):
        safe_name(tree)
        tree_path = root / tree
        if not tree_path.is_dir():
            raise PackageError(f"missing required source tree: {tree}")
        for parent, dirs, files in os.walk(tree_path, followlinks=False):
            for name in dirs + files:
                item = Path(parent) / name
                rel = item.relative_to(root).as_posix()
                if is_link(item):
                    raise PackageError(f"links are forbidden: {rel}")
            dirs[:] = [name for name in dirs if not protected((Path(parent) / name).relative_to(root).as_posix())]
            for name in files:
                rel = (Path(parent) / name).relative_to(root).as_posix()
                if not protected(rel) and rel.casefold() not in sources:
                    raise PackageError(f"source tree file missing from explicit manifest: {rel}")
    # Frontend npm lock must agree with the declared direct dependencies.
    if "frontend-source/package.json" in payload:
        package = json.loads(payload["frontend-source/package.json"])
        lock = json.loads(payload["frontend-source/package-lock.json"])["packages"][""]
        if any(package.get(key, {}) != lock.get(key, {}) for key in ("dependencies", "devDependencies")):
            raise PackageError("frontend dependency declarations disagree with lockfile")
    entries.sort(key=lambda entry: entry["target"])
    inventory = {"schema": "story-continuity-source-inventory-v1",
                 "candidate": manifest["candidate"], "source_only": True,
                 "deployed": False, "files": entries,
                 "manifest_sha256": digest(safe_file(root, manifest_path).read_bytes()),
                 "file_count": len(entries), "total_bytes": total}
    inventory["inventory_sha256"] = digest(encoded(inventory))
    return inventory, payload


def validate_inventory(inventory: dict) -> None:
    raw = dict(inventory)
    expected = raw.pop("inventory_sha256", None)
    if expected != digest(encoded(raw)):
        raise PackageError("inventory checksum mismatch")
    if (inventory.get("schema") != "story-continuity-source-inventory-v1" or
            inventory.get("source_only") is not True or inventory.get("deployed") is not False):
        raise PackageError("invalid source inventory")


def verify_archive(archive_path: Path, expected_inventory: str | None = None) -> dict:
    if archive_path.stat().st_size > MAX_TOTAL_BYTES:
        raise PackageError("archive size limit")
    with tarfile.open(archive_path, "r:gz") as archive:
        seen, data_by_name, total = set(), {}, 0
        for index, member in enumerate(archive):
            if index >= 10000:
                raise PackageError("archive member count limit")
            name = safe_name(member.name)
            if (name.casefold() in seen or protected(name) or not member.isfile() or
                    member.size > MAX_FILE_BYTES or member.size < 0):
                raise PackageError(f"unsafe archive member: {name}")
            total += member.size
            if total > MAX_TOTAL_BYTES:
                raise PackageError("expanded archive size limit")
            seen.add(name.casefold())
            data_by_name[name] = archive.extractfile(member).read()
        if INVENTORY_NAME not in data_by_name:
            raise PackageError("missing source inventory")
        inventory = json.loads(data_by_name.pop(INVENTORY_NAME))
        validate_inventory(inventory)
        if expected_inventory and inventory["inventory_sha256"] != expected_inventory:
            raise PackageError("archive does not match approved inventory")
        files = inventory["files"]
        if len(files) != inventory["file_count"] or len({e["target"].casefold() for e in files}) != len(files):
            raise PackageError("duplicate inventory entry or wrong count")
        if set(data_by_name) != {entry["target"] for entry in files}:
            raise PackageError("archive membership differs from inventory")
        for entry in files:
            name = safe_name(entry["target"])
            if protected(safe_name(entry["source"])):
                raise PackageError("protected inventory source")
            data = data_by_name[name]
            scan_bytes(name, data)
            member = archive.getmember(name)
            expected_mode = 0o755 if name.endswith(".sh") else 0o644
            if (digest(data) != entry["sha256"] or len(data) != entry["bytes"] or
                    member.mode != expected_mode or entry["mode"] != f"0{expected_mode:o}" or
                    member.mtime != 0 or member.uid != 0 or member.gid != 0):
                raise PackageError(f"archive bytes/metadata mismatch: {name}")
        if sum(len(data) for data in data_by_name.values()) != inventory["total_bytes"]:
            raise PackageError("inventory size mismatch")
    return {"verified": True, "source_only": True, "deployed": False,
            "file_count": inventory["file_count"], "inventory_sha256": inventory["inventory_sha256"],
            "archive_sha256": digest(archive_path.read_bytes()), "archive_bytes": archive_path.stat().st_size}


def build_archive(root: Path, manifest_path: str, output: Path, expected_inventory: str) -> dict:
    if not re.fullmatch("[0-9a-f]{64}", expected_inventory or ""):
        raise PackageError("build requires the frozen plan inventory SHA256")
    inventory, payload = make_plan(root, manifest_path)
    if inventory["inventory_sha256"] != expected_inventory:
        raise PackageError("source changed since frozen plan; regenerate and review plan")
    payload[INVENTORY_NAME] = encoded(inventory)
    buffer = io.BytesIO()
    with gzip.GzipFile(filename="", mode="wb", fileobj=buffer, mtime=0, compresslevel=9) as compressed:
        with tarfile.open(mode="w", fileobj=compressed, format=tarfile.PAX_FORMAT) as archive:
            for name, data in sorted(payload.items()):
                member = tarfile.TarInfo(name)
                member.size, member.mtime = len(data), 0
                member.uid = member.gid = 0
                member.uname = member.gname = ""
                member.mode = 0o755 if name.endswith(".sh") else 0o644
                archive.addfile(member, io.BytesIO(data))
    # Re-read every selected source: reject edits during construction.
    after, _ = make_plan(root, manifest_path)
    if after["inventory_sha256"] != expected_inventory:
        raise PackageError("source changed while building archive")
    if is_link(output) or output.exists():
        raise PackageError("output already exists; refusing overwrite")
    output.parent.mkdir(parents=True, exist_ok=True)
    if any(is_link(parent) for parent in output.parents):
        raise PackageError("linked output parent forbidden")
    with output.open("xb") as destination:
        destination.write(buffer.getvalue())
    return verify_archive(output, expected_inventory)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("plan", "build", "verify"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--manifest", default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--archive", type=Path)
    parser.add_argument("--expected-inventory-sha256")
    args = parser.parse_args()
    try:
        if args.action == "plan":
            result, _ = make_plan(args.root, args.manifest)
        elif args.action == "build":
            if not args.output:
                raise PackageError("build requires --output")
            result = build_archive(args.root, args.manifest, args.output, args.expected_inventory_sha256)
        else:
            if not args.archive:
                raise PackageError("verify requires --archive")
            result = verify_archive(args.archive, args.expected_inventory_sha256)
        print(encoded(result).decode("utf-8"), end="")
    except (PackageError, OSError, ValueError, KeyError, tarfile.TarError) as error:
        parser.exit(2, f"maintenance source package rejected: {error}\n")


if __name__ == "__main__":
    main()

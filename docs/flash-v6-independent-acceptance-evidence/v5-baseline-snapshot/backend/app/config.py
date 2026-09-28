from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class ProtectedPathError(ValueError):
    """Raised before a database/reset operation can target a protected path."""


def _resolved(path: Path) -> Path:
    return path.expanduser().resolve()


def _is_within(candidate: Path, parent: Path) -> bool:
    try:
        candidate.relative_to(parent)
        return True
    except ValueError:
        return False


@dataclass(frozen=True)
class AppPaths:
    project_root: Path
    runtime_root: Path
    data_dir: Path
    database_path: Path
    protected_poc_root: Path

    @classmethod
    def from_project_root(
        cls,
        project_root: Path,
        runtime_root: Path | None = None,
        database_path: Path | None = None,
        protected_poc_root: Path | None = None,
    ) -> "AppPaths":
        root = _resolved(project_root)
        runtime = _resolved(runtime_root or root / "runtime")
        data_dir = _resolved(runtime / "data")
        # Keep the local safety boundary without embedding the protected
        # checkout's canonical directory identifier in deployable bytecode.
        protected_name = "-".join(("story", "continuity", "poc"))
        protected = _resolved(protected_poc_root or root.parent / protected_name)
        database = _resolved(database_path or data_dir / "demo.sqlite3")
        return cls(root, runtime, data_dir, database, protected)

    def validate_database_target(self) -> None:
        expected_runtime = _resolved(self.project_root / "runtime")
        expected_data_dir = _resolved(expected_runtime / "data")
        expected_database = _resolved(expected_data_dir / "demo.sqlite3")
        if self.runtime_root != expected_runtime or self.data_dir != expected_data_dir:
            raise ProtectedPathError("runtime target must be this demo's project_root/runtime")
        if self.database_path != expected_database:
            raise ProtectedPathError("database target must be project_root/runtime/data/demo.sqlite3")
        if _is_within(self.database_path, self.protected_poc_root):
            raise ProtectedPathError("database target is inside a protected source root")

    def prepare_runtime(self) -> None:
        self.validate_database_target()
        self.data_dir.mkdir(parents=True, exist_ok=True)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
PATHS = AppPaths.from_project_root(PROJECT_ROOT)

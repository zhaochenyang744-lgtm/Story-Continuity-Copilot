from __future__ import annotations

import argparse
import json
from pathlib import Path

from .config import AppPaths, PROJECT_ROOT
from .stage13 import Stage13Service, Stage13Settings, UnavailableMailer
from .v2_database import V2Database


def main() -> int:
    parser = argparse.ArgumentParser(description="Story Continuity maintenance")
    parser.add_argument("command", choices=("cleanup-visitors",))
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    args = parser.parse_args()
    paths = AppPaths.from_project_root(args.project_root)
    database = V2Database(paths)
    database.initialize()
    service = Stage13Service(database, Stage13Settings.from_env(), UnavailableMailer())
    result = service.cleanup_expired_visitors()
    print(json.dumps({"cleaned": result["visitor_count"], "visitor_hashes": result["visitor_hashes"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

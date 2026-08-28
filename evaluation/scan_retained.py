"""Count sensitive-value findings in retained Stage 6.6 text artifacts without retaining matches."""
from __future__ import annotations

import json
import pathlib
import re


ROOT = pathlib.Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "evaluation" / "results" / "stage66-retained-scan.json"
PATTERNS = {
    "private_key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
    "api_key_value": re.compile(r"(?i)(?:api[_-]?key\s*[:=]\s*[\"']?|sk-)[A-Za-z0-9_-]{16,}"),
    "authorization_value": re.compile(r"(?i)authorization\s*[:=]\s*[\"']?bearer\s+(?!\{|\$)[A-Za-z0-9._-]{12,}"),
    "absolute_path": re.compile(r"[A-Za-z]:\\"),
}


def files_for(scope: str) -> list[pathlib.Path]:
    if scope == "source_config":
        roots = [ROOT / "backend" / "app", ROOT / "backend" / "tests", ROOT / "evaluation", ROOT / "frontend" / "app", ROOT / ".env.example", ROOT / "frontend" / "next.config.mjs"]
        suffixes = {".py", ".ts", ".tsx", ".mjs", ".json", ".example"}
        return [path for root in roots for path in ([root] if root.is_file() else root.rglob("*")) if path.is_file() and path.suffix in suffixes and ".env" not in path.name and "__pycache__" not in path.parts]
    if scope == "frontend_build":
        root = ROOT / "frontend" / ".next" / "static"
        return [path for path in root.rglob("*") if path.is_file() and path.suffix in {".js", ".css", ".json"} and path.suffix != ".map"] if root.exists() else []
    if scope == "retained_logs_eval":
        roots = [ROOT / "evaluation" / "results"]
        return [path for root in roots for path in root.rglob("*") if path.is_file() and ".env" not in path.name and path != OUTPUT and "scan" not in path.name]
    raise ValueError(scope)


def scan(scope: str) -> dict:
    categories = {name: 0 for name in PATTERNS}
    categories.update({"prompt_body_key": 0, "raw_provider_body_key": 0, "chain_of_thought_key": 0})
    count = 0
    for path in files_for(scope):
        try:
            content = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        count += 1
        for name, pattern in PATTERNS.items(): categories[name] += len(pattern.findall(content))
        if scope == "retained_logs_eval":
            lowered = content.casefold()
            categories["prompt_body_key"] += lowered.count('"prompt"') + lowered.count('"prompt_body"')
            categories["raw_provider_body_key"] += lowered.count('"raw_provider_body"') + lowered.count('"provider_body"')
            categories["chain_of_thought_key"] += lowered.count('"reasoning_content"') + lowered.count('"chain_of_thought"')
    return {"text_files": count, "categories": categories, "unresolved": sum(categories.values())}


def main() -> None:
    report = {"evaluation": "scc-web-demo-eval-v1", "scopes": {name: scan(name) for name in ("source_config", "frontend_build", "retained_logs_eval")}}
    report["unresolved"] = sum(value["unresolved"] for value in report["scopes"].values())
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__": main()

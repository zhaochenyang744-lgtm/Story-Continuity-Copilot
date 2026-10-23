"""Read-only corroboration of current provenance, prose repetition and frozen inputs."""
from collections import Counter
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import unicodedata

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
FORBIDDEN = {"eval_set_a1_reserve", "eval_set_a1b_reserve", "eval_set_v13_authoring"}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(value):
    return "".join(c for c in value if not c.isspace() and not unicodedata.category(c).startswith("P"))


def grams(value, names):
    value = "".join(HAN.findall(value))
    for name in sorted(names, key=len, reverse=True):
        value = value.replace("".join(HAN.findall(name)), "|")
    return {part[i:i + 8] for part in value.split("|") for i in range(len(part) - 7)}


def messages(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"input", "request", "question"} and isinstance(item, str):
                yield item
            elif isinstance(item, (dict, list)):
                yield from messages(item)
    elif isinstance(value, list):
        for item in value:
            yield from messages(item)


def main():
    errors = []
    baseline = json.loads((ROOT / "authoring/baseline.json").read_text(encoding="utf-8"))
    protected_matches = {p: digest(REPO / p) == sha for p, sha in baseline["protected"].items()}
    if not all(protected_matches.values()):
        errors.append("protected_file_changed")
    review = json.loads((ROOT / "authoring/independent-review.json").read_text(encoding="utf-8"))
    review_bindings = {p: (ROOT / p).resolve().is_relative_to(ROOT) and (ROOT / p).is_file()
                       and digest(ROOT / p) == sha for p, sha in review["bindings"].items()}
    if len(review_bindings) != 10 or not all(review_bindings.values()):
        errors.append("independent_review_binding_mismatch")
    if review.get("status") != "PASS" or review.get("unresolved_count") != 0 or review["coverage"]["tasks"].get("count") != 18:
        errors.append("independent_review_incomplete")
    text_format_errors = [p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file()
                          and (b"\r" in p.read_bytes() or p.read_bytes().startswith(b"\xef\xbb\xbf"))]
    if text_format_errors:
        errors.append("text_format")
    snapshot = json.loads((ROOT / "authoring/novelty-reference.json").read_text(encoding="utf-8"))
    sources = {v["path"]: v for v in snapshot["sources"]}
    evaluation = ROOT.parent
    current = {}
    old_files = []
    for base, directories, files in os.walk(evaluation, followlinks=False):
        directories[:] = sorted(d for d in directories if d not in FORBIDDEN and d != ROOT.name
                                and not (Path(base) / d).is_symlink()
                                and not (getattr((Path(base) / d).lstat(), "st_file_attributes", 0) & 0x400))
        if "tasks.json" in files:
            p = Path(base) / "tasks.json"
            raw = p.read_bytes()
            value = json.loads(raw.decode("utf-8-sig"))
            current[p.relative_to(evaluation).as_posix()] = {
                "sha256": hashlib.sha256(raw).hexdigest(),
                "inputs": sorted({normalize(s) for s in messages(value) if normalize(s)})}
        if any(p.startswith("eval_set") for p in Path(base).parts):
            old_files.extend(Path(base) / f for f in files if f.endswith((".md", ".json")))
    if set(current) != set(sources):
        errors.append("historical_source_inventory_changed")
    for path in current.keys() & sources.keys():
        if current[path]["sha256"] != sources[path]["sha256"] or current[path]["inputs"] != sources[path]["inputs"]:
            errors.append("historical_source_or_inputs_changed:" + path)
    tasks = json.loads((ROOT / "tasks.json").read_text(encoding="utf-8"))
    names = tasks["works"][0]["names"]
    name_hits = set()
    for path in old_files:
        if path.is_symlink():
            continue
        value = path.read_text(encoding="utf-8-sig")
        name_hits.update(n for n in names if n in value)
    if name_hits:
        errors.append("proper_name_overlap")
    source = (ROOT / "works/w01.md").read_text(encoding="utf-8")
    bodies = re.split(r"^# 第[0-9]+章 [^\r\n]+$", source, flags=re.MULTILINE)[1:]
    reference_grams = set().union(*(grams(body, names) for body in bodies))
    shared_draft_copy8 = len(reference_grams & grams(tasks["works"][0]["shared_draft"]["body"], names))
    if shared_draft_copy8:
        errors.append("shared_draft_copy8")
    paragraphs = ["".join(HAN.findall(p)) for p in source.split("\n\n") if not p.startswith("#")]
    duplicated_paragraphs = sum(count - 1 for text, count in Counter(paragraphs).items() if len(text) >= 40 and count > 1)
    if duplicated_paragraphs:
        errors.append("exact_long_paragraph_repetition")
    historical = [s for item in sources.values() for s in item["inputs"]]
    maxima = []
    for task in tasks["tasks"]:
        value = task.get("input", task.get("request", ""))
        ratio = max((difflib.SequenceMatcher(None, normalize(value), s).ratio() for s in historical), default=0.0)
        maxima.append({"id": task["id"], "max_similarity_all_historical": round(ratio, 6)})
        if ratio >= 0.8:
            errors.append("novelty:" + task["id"])
    output = {"status": "FAIL" if errors else "PASS", "protected_files_byte_identical": protected_matches,
              "independent_review_status": review["status"], "independent_review_tasks": review["coverage"]["tasks"]["count"],
              "independent_review_bindings": review_bindings, "text_format_errors": text_format_errors,
              "historical_source_inventory_matches": set(current) == set(sources), "historical_sources": len(current),
              "historical_inputs": len(historical), "proper_name_overlap": len(name_hits),
              "old_markdown_json_files_scanned": len(old_files), "paragraphs_checked": len(paragraphs),
              "shared_draft_copy8_errors": shared_draft_copy8,
              "exact_long_paragraph_repetition": duplicated_paragraphs, "novelty_full_comparison": maxima,
              "errors": errors, "model_calls": 0}
    (ROOT / "authoring/final-audit.json").write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))
    return int(bool(errors))


if __name__ == "__main__":
    raise SystemExit(main())

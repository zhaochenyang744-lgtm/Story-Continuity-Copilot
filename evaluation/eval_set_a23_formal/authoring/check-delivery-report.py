"""Read-only leakage check for the fixed external delivery report.

Run with the task's Python interpreter and ``-X utf8 -B``.  There are no
arguments, writes, network calls, product calls, or evaluation calls.  Relative
source paths resolve from this file, so the current directory does not matter.

Exit codes: 0 = PASS, 1 = FAIL, 2 = report not present.  A missing report emits
only {"status":"missing"}, without loading the sealed source files.  All other
results contain structural IDs and counts, never report or source excerpts.
Counts are matched protected source entries (one per entry/category), not the
number of repeated occurrences in the report.  The Han-fragment category counts
matched uninterrupted source Han runs, not every overlapping 12-character window.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Any


REPORT_PATH = Path("C:/Users/赵晨阳/Desktop/v2.0任务/16-交付报告.md")
REPO_ROOT = Path(__file__).resolve().parents[3]
SET_PATHS = (
    ("formal", REPO_ROOT / "evaluation" / "eval_set_a23_formal"),
    ("safety", REPO_ROOT / "evaluation" / "eval_set_a2s3_formal"),
)
HAN_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\U00020000-\U0002fa1f]+")
CHAPTER_HEADING = re.compile(r"(?m)^#\s+第\d+章\s+([^\r\n]+)$")
SENTENCE = re.compile(r"[^。！？!?\r\n]+[。！？!?]+(?:[”’\"']*)")
WINDOW = 12
CATEGORIES = (
    "new_name",
    "work_title",
    "chapter_title",
    "request",
    "input",
    "evidence_quote",
    "self_review_quote",
    "injection_text",
    "after_point",
    "draft_sentence",
    "draft_paragraph",
    "material_content",
    "metadata_content",
    "prose_han12",
)


@dataclass(frozen=True)
class Protected:
    category: str
    source_id: str
    text: str


class SourceError(Exception):
    def __init__(self, code: str, source_id: str) -> None:
        super().__init__(code)
        self.code = code
        self.source_id = source_id


def normalized(text: str) -> str:
    return unicodedata.normalize("NFKC", text)


def compact(text: str) -> str:
    """Ignore layout whitespace while retaining punctuation and table boundaries."""
    return "".join(normalized(text).split())


def text_file(path: Path, source_id: str) -> str:
    try:
        return path.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        raise SourceError("source_read_error", source_id) from None


def json_file(path: Path, source_id: str) -> Any:
    try:
        return json.loads(text_file(path, source_id))
    except (json.JSONDecodeError, ValueError):
        raise SourceError("source_json_error", source_id) from None


def inside_set(set_root: Path, relative: Any, source_id: str) -> Path:
    if not isinstance(relative, str) or not relative:
        raise SourceError("source_schema_error", source_id)
    supplied = Path(relative)
    if supplied.is_absolute():
        raise SourceError("source_path_error", source_id)
    resolved = (set_root / supplied).resolve()
    try:
        resolved.relative_to(set_root.resolve())
    except ValueError:
        raise SourceError("source_path_error", source_id) from None
    return resolved


def strings_with_keys(value: Any, key: str) -> list[str]:
    """Collect a known field recursively, without using source keys in output IDs."""
    found: list[str] = []
    if isinstance(value, dict):
        selected = value.get(key)
        if isinstance(selected, str):
            found.append(selected)
        elif isinstance(selected, list):
            found.extend(item for item in selected if isinstance(item, str))
        for child in value.values():
            found.extend(strings_with_keys(child, key))
    elif isinstance(value, list):
        for child in value:
            found.extend(strings_with_keys(child, key))
    return found


def all_strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for child in value.values() for text in all_strings(child)]
    if isinstance(value, list):
        return [text for child in value for text in all_strings(child)]
    return []


def load_sources() -> tuple[list[Protected], list[tuple[str, str]]]:
    protected: list[Protected] = []
    prose: list[tuple[str, str]] = []

    def add(category: str, prefix: str, texts: list[str]) -> None:
        for index, text in enumerate(texts, 1):
            if text.strip():
                protected.append(Protected(category, f"{prefix}.{index:04d}", text))

    for label, set_root in SET_PATHS:
        data = json_file(set_root / "tasks.json", f"{label}.tasks")
        if not isinstance(data, dict):
            raise SourceError("source_schema_error", f"{label}.tasks")
        works, tasks = data.get("works"), data.get("tasks")
        if not isinstance(works, list) or not works or not isinstance(tasks, list) or not tasks:
            raise SourceError("source_schema_error", f"{label}.tasks")

        for work_index, work in enumerate(works, 1):
            work_id = f"{label}.work.{work_index:04d}"
            if not isinstance(work, dict):
                raise SourceError("source_schema_error", work_id)
            names, title = work.get("names"), work.get("title")
            if (not isinstance(names, list) or not names
                    or any(not isinstance(name, str) or not name for name in names)
                    or not isinstance(title, str) or not title):
                raise SourceError("source_schema_error", work_id)
            add("new_name", f"{work_id}.name", names)
            add("work_title", f"{work_id}.title", [title])

            body_path = inside_set(set_root, work.get("source_file"), f"{work_id}.body")
            body = text_file(body_path, f"{work_id}.body")
            prose.append((f"{work_id}.body", body))
            add("chapter_title", f"{work_id}.chapter_title", CHAPTER_HEADING.findall(body))

            draft = work.get("shared_draft")
            if (not isinstance(draft, dict) or not isinstance(draft.get("body"), str)
                    or not draft["body"].strip()
                    or not isinstance(draft.get("chapter_title"), str)
                    or not draft["chapter_title"].strip()):
                raise SourceError("source_schema_error", f"{work_id}.draft")
            draft_body = draft["body"]
            add("chapter_title", f"{work_id}.draft_title", [draft["chapter_title"]])
            add("draft_sentence", f"{work_id}.draft_sentence", SENTENCE.findall(draft_body))
            paragraphs = [part.strip() for part in re.split(r"\r?\n\s*\r?\n", draft_body)]
            add("draft_paragraph", f"{work_id}.draft_paragraph", paragraphs)
            prose.append((f"{work_id}.draft", draft_body))

            materials = work.get("materials")
            if not isinstance(materials, dict):
                raise SourceError("source_schema_error", f"{work_id}.materials")
            for material_index, field in enumerate(("facts", "foreshadows"), 1):
                material_id = f"{work_id}.material.{material_index:04d}"
                path = inside_set(set_root, materials.get(field), material_id)
                material = json_file(path, material_id)
                if not isinstance(material, list):
                    raise SourceError("source_schema_error", material_id)
                # Human content only; machine status/type values remain reportable.
                human_fields = ("subject", "predicate", "value", "title", "description")
                content: list[str] = []
                protected_content: list[str] = []
                for entry in material:
                    if not isinstance(entry, dict):
                        raise SourceError("source_schema_error", material_id)
                    for human_field in human_fields:
                        text = entry.get(human_field)
                        if isinstance(text, str):
                            prose.append((f"{material_id}.text.{len(content) + 1:04d}", text))
                            content.append(text)
                            # Values and thread titles/descriptions are content even
                            # when short.  Generic subject/attribute labels get the
                            # threshold; names and all action points have none.
                            if (human_field in ("value", "title", "description")
                                    or len("".join(HAN_RUN.findall(text))) >= 8):
                                protected_content.append(text)
                add("material_content", f"{material_id}.content", protected_content)

        for task_index, task in enumerate(tasks, 1):
            task_id = f"{label}.task.{task_index:04d}"
            if not isinstance(task, dict):
                raise SourceError("source_schema_error", task_id)
            for key, category in (
                ("request", "request"), ("input", "input"),
                ("evidence_quotes", "evidence_quote"), ("after_points", "after_point"),
            ):
                add(category, f"{task_id}.{category}", strings_with_keys(task, key))
            injection = task.get("injection")
            if isinstance(injection, dict) and isinstance(injection.get("text"), str):
                add("injection_text", f"{task_id}.injection", [injection["text"]])
            reasons = strings_with_keys(task, "why")
            add("metadata_content", f"{task_id}.why", reasons)
            for text_index, text in enumerate(all_strings(task), 1):
                prose.append((f"{task_id}.text.{text_index:04d}", text))

        review_id = f"{label}.self_review"
        review = json_file(set_root / "authoring" / "self-review.json", review_id)
        if not isinstance(review, dict) or not isinstance(review.get("works"), dict):
            raise SourceError("source_schema_error", review_id)
        add("self_review_quote", f"{review_id}.quote", strings_with_keys(review, "quote"))
        for text_index, text in enumerate(all_strings(review), 1):
            prose.append((f"{review_id}.text.{text_index:04d}", text))

    return protected, prose


def check(report: str, protected: list[Protected], prose: list[tuple[str, str]]) -> dict[str, Any]:
    report_compact = compact(report)
    counts = {category: 0 for category in CATEGORIES}
    errors: list[dict[str, str]] = []
    for item in protected:
        needle = compact(item.text)
        if needle and needle in report_compact:
            counts[item.category] += 1
            errors.append({"category": item.category, "id": item.source_id})

    # A Han run stops at every punctuation mark, digit, Latin character, whitespace,
    # Markdown table separator, etc.  No stripping/joining across such boundaries.
    report_windows = {
        run[offset:offset + WINDOW]
        for run in HAN_RUN.findall(normalized(report))
        for offset in range(len(run) - WINDOW + 1)
    }
    if report_windows:
        for source_id, source_text in prose:
            for run_index, run in enumerate(HAN_RUN.findall(normalized(source_text)), 1):
                if len(run) < WINDOW:
                    continue
                if any(run[offset:offset + WINDOW] in report_windows
                       for offset in range(len(run) - WINDOW + 1)):
                    counts["prose_han12"] += 1
                    errors.append({
                        "category": "prose_han12",
                        "id": f"{source_id}.hanrun.{run_index:06d}",
                    })
    return {"status": "FAIL" if errors else "PASS", "counts": counts, "errors": errors}


def emit(result: dict[str, Any]) -> None:
    print(json.dumps(result, ensure_ascii=True, separators=(",", ":")))


def main() -> int:
    try:
        if not REPORT_PATH.exists():
            emit({"status": "missing"})
            return 2
        report = REPORT_PATH.read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        emit({"status": "FAIL", "counts": {"read_error": 1},
              "errors": [{"category": "report_read_error", "id": "report"}]})
        return 1
    try:
        protected, prose = load_sources()
        result = check(report, protected, prose)
    except SourceError as error:
        result = {"status": "FAIL", "counts": {"source_error": 1},
                  "errors": [{"category": error.code, "id": error.source_id}]}
    except Exception:
        # Exception messages and tracebacks can embed sealed strings.  Fail closed
        # with a fixed code; never print the exception or source/report snippets.
        result = {"status": "FAIL", "counts": {"internal_error": 1},
                  "errors": [{"category": "internal_error", "id": "runtime"}]}
    emit(result)
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())

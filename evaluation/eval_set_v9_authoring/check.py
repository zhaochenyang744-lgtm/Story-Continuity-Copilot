"""Format and product-constraint check for the V9 held-out authoring file.

Checks structure only; it never judges whether an expected answer is right.
Usage: python evaluation/eval_set_v9_authoring/check.py [path-to-cases.json]
"""
from __future__ import annotations

import collections
import json
import pathlib
import re
import sys

HERE = pathlib.Path(__file__).resolve().parent
CLASSES = ("conflict", "no_conflict", "insufficient_evidence")
CATEGORIES = ("attribute", "object_state", "relationship", "character_knowledge",
              "timeline", "event_status", "location_action", "world_rule")
MAX_BODY = 300
TIME = re.compile(r"\d{1,2}:\d{2}|\d{1,2}\s*(?:am|pm)\b|[\d一二三四五六七八九十两]+\s*(?:点|时)|"
                  r"第\s*[\d一二三四五六七八九十]+\s*天|\d{4}-\d{2}-\d{2}|"
                  r"[\d一二三四五六七八九十]+\s*[月日号]|今天|今日|昨天|昨日|明天|前天|"
                  r"\b(?:today|yesterday|tomorrow|day\s+\w+)\b", re.IGNORECASE)


def main(path: pathlib.Path) -> int:
    errors, warnings = [], []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        print(f"ERROR 无法读取 {path}: {error}")
        return 1
    corpora = {}
    for corpus in data.get("corpora", []):
        key = corpus.get("key")
        if not key or key in corpora:
            errors.append(f"作品 key 缺失或重复: {key!r}")
            continue
        labels = {}
        for chapter in corpus.get("chapters", []):
            label, body = chapter.get("label"), chapter.get("body")
            if not isinstance(label, str) or not re.fullmatch(r"[a-z][a-z0-9_]{0,40}", label or ""):
                errors.append(f"{key}: 章节标签需为英文小写/数字/下划线: {label!r}")
            elif label in labels:
                errors.append(f"{key}: 章节标签重复: {label}")
            if not isinstance(body, str) or not body.strip():
                errors.append(f"{key}/{label}: 正文为空")
            elif len(body) > MAX_BODY:
                errors.append(f"{key}/{label}: 正文 {len(body)} 字，超过 {MAX_BODY}")
            if not isinstance(chapter.get("is_rule"), bool):
                errors.append(f"{key}/{label}: is_rule 必须是 true 或 false")
            labels[label] = chapter
        if not 3 <= len(labels) <= 12:
            warnings.append(f"{key}: 有 {len(labels)} 个章节，建议 6-10 个")
        corpora[key] = labels
    if not corpora:
        errors.append("没有任何作品")

    cases = data.get("cases", [])
    ids = collections.Counter(case.get("id") for case in cases)
    errors += [f"题目 id 重复: {i}" for i, n in ids.items() if n > 1 or not i]
    drafts = collections.Counter(case.get("draft") for case in cases)
    errors += [f"草稿句重复: {d}" for d, n in drafts.items() if n > 1]
    by_class = collections.Counter(case.get("expected_class") for case in cases)
    if len(cases) != 36:
        errors.append(f"题目数为 {len(cases)}，应为 36")
    for name in CLASSES:
        if by_class.get(name, 0) != 12:
            errors.append(f"{name} 有 {by_class.get(name, 0)} 题，应为 12")
    unknown = set(by_class) - set(CLASSES)
    if unknown:
        errors.append(f"未知的 expected_class: {sorted(map(str, unknown))}")

    conflict_categories, designated = collections.Counter(), []
    for case in cases:
        cid, key = case.get("id"), case.get("corpus")
        draft = case.get("draft") or ""
        if key not in corpora:
            errors.append(f"{cid}: 作品 {key!r} 不存在")
            continue
        evidence = case.get("evidence") or []
        missing = [label for label in evidence if label not in corpora[key]]
        if not evidence or missing:
            errors.append(f"{cid}: evidence 为空或引用了不存在的章节 {missing}")
            continue
        if not draft.strip():
            errors.append(f"{cid}: draft 为空")
        if any(draft.strip() == corpora[key][label]["body"].strip() for label in evidence):
            warnings.append(f"{cid}: 草稿句与原文逐字相同")
        category = case.get("category")
        if case.get("expected_class") == "conflict":
            if category not in CATEGORIES:
                errors.append(f"{cid}: 冲突题必须填写 8 个类别之一，当前 {category!r}")
            conflict_categories[category] += 1
            has_rule = any(corpora[key][label].get("is_rule") for label in evidence)
            draft_times = {t.lower().replace(" ", "") for t in TIME.findall(draft)}
            shared = any(draft_times & {t.lower().replace(" ", "") for t in TIME.findall(corpora[key][label]["body"])}
                         for label in evidence)
            if not has_rule and not shared:
                errors.append(f"{cid}: 冲突题既没有 is_rule 章节，也没有与证据共享的明确时间（见说明“硬性约束”）")
            if case.get("designated_regression") is True:
                designated.append(cid)
        else:
            if category is not None:
                errors.append(f"{cid}: 非冲突题的 category 应为 null")
            if case.get("designated_regression") is True:
                errors.append(f"{cid}: 只有冲突题可以标 designated_regression")
        if not isinstance(case.get("designated_regression"), bool):
            errors.append(f"{cid}: designated_regression 必须是 true 或 false")
    uncovered = [c for c in CATEGORIES if not conflict_categories.get(c)]
    if uncovered:
        warnings.append(f"冲突题未覆盖的类别: {uncovered}")
    if len(designated) != 3:
        errors.append(f"designated_regression 应恰好 3 题，当前 {len(designated)}")
    languages = collections.Counter(corpus.get("language") for corpus in data.get("corpora", []))

    for line in errors:
        print("ERROR", line)
    for line in warnings:
        print("WARN ", line)
    print(f"作品 {len(corpora)} 部，题目 {len(cases)}，分布 {dict(by_class)}，冲突类别 {dict(conflict_categories)}，语言 {dict(languages)}")
    print("检查通过" if not errors else f"共 {len(errors)} 个 ERROR")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else HERE / "cases.json"))

"""Read-only, account-scoped manuscript and author-material exports.

All database reads share one SQLite snapshot. No paths, account records,
provider payloads, historical drafts, or credentials enter the export.
"""
from __future__ import annotations

import hashlib
import io
import json
import re
import sqlite3
import unicodedata
import zipfile
from datetime import datetime, timezone
from typing import Callable, Literal
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import Response

from .database import DomainError
from .text_content import visible_draft_text
from .v2_database import V2Database

ExportFormat = Literal["txt", "markdown", "bundle"]
MAX_EXPORT_BYTES = 64 * 1024 * 1024
INCOMPLETE_MANUSCRIPT_NOTICE = (
    "导出范围提示：部分已入库章节未保存完整正文；下文仅附已保存的来源片段或缺失标记，"
    "不能视为完整作品原稿。"
)


def _select(row, names: str) -> dict:
    return {name: row[name] for name in names.split()}


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _chapter_format(c: sqlite3.Connection, project_id: str, chapter) -> str:
    # New chapter revisions may explicitly store their representation.
    if "body_format" in chapter.keys() and chapter["body_format"] in {"plain_text", "markdown"}:
        return chapter["body_format"]
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='v2_chapter_content_formats'").fetchone():
        stored = c.execute(
            "SELECT body_format FROM v2_chapter_content_formats WHERE chapter_id=? AND source_revision=?",
            (chapter["id"], chapter["source_revision"]),
        ).fetchone()
        if stored:
            return stored["body_format"]
    # Existing completed rich drafts retain their format on the immutable
    # draft revision bound to the committed append operation.
    row = c.execute(
        """SELECT f.body_format FROM v2_source_change_sets s
           JOIN v2_draft_content_formats f ON f.draft_id=s.draft_id AND f.revision=s.draft_revision
           WHERE s.project_id=? AND s.target_source_revision=? AND s.status='committed'
             AND s.input_method='draft_complete' ORDER BY s.committed_at DESC,s.id LIMIT 1""",
        (project_id, chapter["source_revision"]),
    ).fetchone()
    return row["body_format"] if row else "plain_text"


def project_snapshot(db: V2Database, user_id: str, project_id: str, include_draft: bool = False) -> dict:
    """Return detached current content, with a digest of that exact snapshot."""
    with db.connection() as c:
        c.execute("PRAGMA query_only=ON")
        c.execute("BEGIN")
        project = db._project(c, user_id, project_id)
        chapters = []
        for row in c.execute("SELECT * FROM v2_chapters WHERE project_id=? ORDER BY chapter_number,id", (project_id,)):
            chapter = _select(row, "id chapter_number title summary body source_revision")
            chapter["body_format"] = _chapter_format(c, project_id, row)
            chapters.append(chapter)
        current_sources = [
            dict(row) for row in c.execute(
                """SELECT s.id,s.chapter_id,s.label,s.body,s.source_revision
                   FROM v2_source_spans s JOIN v2_chapters ch ON ch.id=s.chapter_id AND ch.project_id=s.project_id
                   WHERE s.project_id=? AND s.source_revision=ch.source_revision
                   ORDER BY ch.chapter_number,s.rowid""", (project_id,)
            )
        ]
        sources_by_chapter = {}
        for source in current_sources:
            sources_by_chapter.setdefault(source["chapter_id"], []).append(source)
        for chapter in chapters:
            has_body = bool(chapter["body"].strip())
            fragments = sources_by_chapter.get(chapter["id"], []) if not has_body else []
            chapter["body_origin"] = "chapter_body" if has_body else "source_fragments" if fragments else "unavailable"
            chapter["has_complete_body"] = has_body
            # Keep the persisted body unchanged. Fragments have separate IDs and
            # labels; joining them must never manufacture a full chapter body.
            chapter["source_fragments"] = fragments
        complete_count = sum(chapter["has_complete_body"] for chapter in chapters)
        fragment_count = sum(chapter["body_origin"] == "source_fragments" for chapter in chapters)
        completeness = {
            "status": "no_committed_chapters" if not chapters else
                      "complete_stored_chapters" if complete_count == len(chapters) else "partial_stored_chapters",
            "all_committed_chapter_bodies_present": bool(chapters) and complete_count == len(chapters),
            "total_chapters": len(chapters),
            "complete_body_chapters": complete_count,
            "fragment_only_chapters": fragment_count,
            "missing_body_chapters": len(chapters) - complete_count - fragment_count,
            "meaning": "completeness_of_stored_chapter_bodies_only_not_story_completion",
        }
        current_source_ids = {row["id"] for row in current_sources}
        drafts = []
        if include_draft:
            row = c.execute(
                """SELECT * FROM v2_drafts WHERE project_id=? AND status IN ('draft','saved')
                   ORDER BY saved_at DESC,id DESC LIMIT 1""", (project_id,)
            ).fetchone()
            if row and row["body"].strip():
                if row["chapter_number"] in {ch["chapter_number"] for ch in chapters}:
                    raise DomainError("export_draft_overlaps_chapter", 409)
                draft = _select(row, "id chapter_number title body revision status saved_at")
                draft["body_format"] = db._draft_body_format(c, row["id"], row["revision"])
                drafts.append(draft)
        materials = [
            db._material_public(row)
            for row in c.execute("SELECT * FROM v2_author_materials WHERE project_id=? ORDER BY kind,created_at,id", (project_id,))
        ]
        # Project legacy plans without triggering their lazy database migration.
        known_material_ids = {row["id"] for row in materials}
        for kind, spec in db._AUTHOR_INTENT.items():
            for row in c.execute(f"SELECT * FROM {spec['table']} WHERE project_id=? ORDER BY position,id", (project_id,)):
                projected = db._legacy_material(kind, row)
                if projected["id"] not in known_material_ids:
                    materials.append(db._material_public(projected))
        confirmed_facts, facts_needing_review, inactive_facts = [], [], []
        for row in c.execute(
            """SELECT id,memory_type,subject,predicate,value,source_span_id,review_status,valid_from,valid_to
               FROM v2_memory_records WHERE project_id=? AND version=?
               AND review_status IN ('author_confirmed','needs_review','source_revised')
               ORDER BY memory_type,subject,predicate,id""", (project_id, project["current_memory_version"])
        ):
            record = dict(row)
            source_is_current = not record["source_span_id"] or record["source_span_id"] in current_source_ids
            record["source_is_current"] = source_is_current
            version = project["current_memory_version"]
            active = (record["valid_from"] is None or record["valid_from"] <= version) and (record["valid_to"] is None or record["valid_to"] >= version)
            target = inactive_facts if not active else confirmed_facts if source_is_current and record["review_status"] == "author_confirmed" else facts_needing_review
            target.append(record)
        characters = []
        for row in c.execute("SELECT * FROM v2_characters WHERE project_id=? ORDER BY name,id", (project_id,)):
            item = _select(row, "id name role_type identity goal current_state knowledge_boundary")
            item["relationships"] = json.loads(row["relationships_json"])
            item["aliases"] = [
                alias["alias"] for alias in c.execute(
                    "SELECT alias FROM v2_character_aliases WHERE project_id=? AND character_id=? AND status='active' ORDER BY created_at,id",
                    (project_id, row["id"]),
                )
            ]
            characters.append(item)
        snapshot = {
            "schema_version": "project-export-v1",
            "scope": {
                "manuscript": "current_committed_chapters",
                "draft": "current_saved_nonempty_draft" if include_draft else "excluded",
                "unsaved_browser_edits_included": False,
                "historical_chapter_revisions_included": False,
                "archived_materials_included": True,
                "facts": "current_memory_version_author_confirmed_with_current_sources",
            },
            "completeness": completeness,
            "project": _select(project, "id title genre summary status metadata_revision source_revision current_memory_version author_context_version updated_at"),
            "chapters": chapters,
            "drafts": drafts,
            "sources": current_sources,
            "author_materials": materials,
            "outline": [dict(row) for row in c.execute(
                "SELECT id,chapter_number,title,summary,status FROM v2_outline_nodes WHERE project_id=? ORDER BY chapter_number,id", (project_id,)
            )],
            "characters": characters,
            "world_entries": [dict(row) for row in c.execute(
                "SELECT id,entry_type,name,summary FROM v2_world_entries WHERE project_id=? ORDER BY name,id", (project_id,)
            )],
            "confirmed_facts": confirmed_facts,
            "facts_needing_review": facts_needing_review,
            "inactive_facts": inactive_facts,
            "foreshadows": [dict(row) for row in c.execute(
                """SELECT id,title,description,status,planted_chapter_id,planted_source_span_id,resolved_chapter_id,
                          resolved_source_span_id,version,archived_at FROM v2_foreshadows
                   WHERE project_id=? ORDER BY created_at,id""", (project_id,)
            )],
            "revision_tasks": [dict(row) for row in c.execute(
                """SELECT id,title,instruction,priority,position,status,version FROM v2_revision_tasks
                   WHERE project_id=? ORDER BY position,id""", (project_id,)
            )],
        }
    snapshot["snapshot_sha256"] = hashlib.sha256(_json_bytes(snapshot)).hexdigest()
    snapshot["exported_at"] = datetime.now(timezone.utc).isoformat()
    return snapshot


def _markdown_literal(value: str) -> str:
    # Plain-text asterisks, HTML and headings must stay literal in Markdown.
    value = value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|~])", r"\\\1", value)


def _heading(value: str) -> str:
    return _markdown_literal(" ".join(value.splitlines()))


def manuscript(snapshot: dict, markdown: bool) -> bytes:
    title = snapshot["project"]["title"]
    parts = [f"# {_heading(title)}" if markdown else title]
    completeness = snapshot["completeness"]
    if completeness["status"] == "partial_stored_chapters":
        parts.append(INCOMPLETE_MANUSCRIPT_NOTICE)
    elif completeness["status"] == "no_committed_chapters":
        parts.append("当前作品尚无已入库章节正文。")
    for chapter in snapshot["chapters"]:
        heading = chapter["title"] or f"第 {chapter['chapter_number']} 章"
        body = chapter["body"]
        if not chapter["has_complete_body"]:
            if chapter["source_fragments"]:
                heading += " · 来源片段，非完整章节"
                fragments = [
                    f"【来源片段 {index} · {source['label']}】\n\n{source['body']}"
                    for index, source in enumerate(chapter["source_fragments"], 1)
                ]
                body = "\n\n".join(fragments)
            else:
                heading += " · 完整正文缺失"
                body = "本章节未保存完整正文，也没有当前版本的可导出来源片段。"
            body_format = "plain_text"
        else:
            body_format = chapter["body_format"]
        if markdown:
            body = body if body_format == "markdown" else _markdown_literal(body)
            parts.append(f"## {_heading(heading)}\n\n{body}")
        else:
            parts.append(f"{heading}\n\n{visible_draft_text(body, body_format)}")
    for draft in snapshot["drafts"]:
        heading = f"未入库草稿 · 第 {draft['chapter_number']} 章 · {draft['title']}"
        body = draft["body"]
        if markdown:
            body = body if draft["body_format"] == "markdown" else _markdown_literal(body)
            parts.append(f"## {_heading(heading)}\n\n{body}")
        else:
            parts.append(f"{heading}\n\n{visible_draft_text(body, draft['body_format'])}")
    return ("\n\n".join(parts) + "\n").encode("utf-8")


def materials_markdown(snapshot: dict) -> bytes:
    parts = [f"# {_heading(snapshot['project']['title'])} · 创作资料",
             "作者规划与设定保留其原有性质；已确认事实和来源待复核记录分别列出。"]
    names = {"story": "故事规划", "character": "人物资料", "world": "世界设定"}
    natures = {"setting": "设定", "plan": "规划", "idea": "想法"}
    for kind, label in names.items():
        parts.append(f"## {label}")
        items = [item for item in snapshot["author_materials"] if item["kind"] == kind]
        for item in items:
            state = "已归档" if item["archived"] else "当前"
            parts.append(f"### {_heading(item['title'])}\n\n性质：{natures.get(item['nature'], item['nature'])}；{state}\n\n"
                         f"{_markdown_literal(item['content'])}\n\n知情边界：{_markdown_literal(item['knowledge']) or '未填写'}\n\n"
                         f"披露状态：{item['disclosure']}；适用章节：{item['from'] or '不限'} — {item['to'] or '不限'}")
        if not items:
            parts.append("暂无资料。")
    parts.append("## 已有角色卡")
    for item in snapshot["characters"]:
        parts.append(f"### {_heading(item['name'])}\n\n身份：{_markdown_literal(item['identity'])}\n\n"
                     f"目标：{_markdown_literal(item['goal'])}\n\n当前状态：{_markdown_literal(item['current_state'])}\n\n"
                     f"知情边界：{_markdown_literal(item['knowledge_boundary'])}\n\n"
                     f"别名：{_markdown_literal('、'.join(item['aliases'])) or '暂无'}")
    parts.append("## 已有世界条目")
    for item in snapshot["world_entries"]:
        parts.append(f"### {_heading(item['name'])}\n\n{_markdown_literal(item['summary'])}")
    parts.append("## 章节大纲")
    for item in snapshot["outline"]:
        parts.append(f"### 第 {item['chapter_number']} 章 · {_heading(item['title'])}\n\n{_markdown_literal(item['summary'])}\n\n状态：{item['status']}")
    for key, label in (("confirmed_facts", "已确认事实"), ("facts_needing_review", "来源待复核记录"), ("inactive_facts", "已失效记录")):
        parts.append(f"## {label}")
        for item in snapshot[key]:
            parts.append(f"- {_markdown_literal(item['subject'])} · {_markdown_literal(item['predicate'])}：{_markdown_literal(item['value'])}")
        if not snapshot[key]:
            parts.append("暂无记录。")
    parts.append("## 其他资料\n\n章节大纲、已有角色卡与别名、世界条目、伏笔和修订任务完整保存在 snapshot.json。正文原始格式与版本号也在该文件中保留。")
    return ("\n\n".join(parts) + "\n").encode("utf-8")


def export_content(snapshot: dict, format: ExportFormat) -> tuple[bytes, str, str]:
    """Render only detached values; ZIP members have fixed, safe names."""
    if format == "txt":
        content, mime, extension = manuscript(snapshot, False), "text/plain", "txt"
    elif format == "markdown":
        content, mime, extension = manuscript(snapshot, True), "text/markdown", "md"
    elif format == "bundle":
        files = {
            "manuscript.txt": manuscript(snapshot, False),
            "manuscript.md": manuscript(snapshot, True),
            "materials.md": materials_markdown(snapshot),
            "snapshot.json": _json_bytes(snapshot),
            "README.txt": (
                "Story Continuity Copilot 作品导出\n\n"
                "manuscript.txt：当前已保存章节内容，按章节号排列；Markdown 格式转换为可读文字。\n"
                "manuscript.md：当前已保存章节内容，保留富文本草稿的 Markdown 表达。\n"
                "未保存完整正文的章节仅附当前来源片段或缺失标记，并明确标注非完整章节。\n"
                "若勾选草稿，文件末尾附当前已保存、未入库的非空草稿，并单独标明。\n"
                "materials.md：规划、人物、世界设定和已确认事实的阅读版。\n"
                "snapshot.json：正文原始字符串、内容格式、章节版本及全部创作资料的精确快照。\n"
                "snapshot_sha256：删除 exported_at 与 snapshot_sha256 后，以 UTF-8、ensure_ascii=False、"
                "indent=2、sort_keys=True JSON 加末尾换行计算 SHA-256。\n"
                "checksums.json：除该文件本身以外，每个压缩包文件的 SHA-256。\n"
                "本次导出范围保存在 snapshot.json 的 scope；浏览器未保存输入不在快照中。\n"
                "completeness 说明已入库章节正文的完整程度；chapter.body_origin 区分正文、来源片段与缺失。\n"
                "chapter.body 保留数据库原值；来源片段保存在 source_fragments，不能当作完整原稿。\n"
                "正文采用当前章节版本；历史修订保留在应用内。已归档资料在资料包中有明确标记。\n"
                + (INCOMPLETE_MANUSCRIPT_NOTICE + "\n" if snapshot["completeness"]["status"] == "partial_stored_chapters" else "")
            ).encode("utf-8"),
        }
        if sum(map(len, files.values())) > MAX_EXPORT_BYTES:
            raise DomainError("export_too_large", 413)
        files["checksums.json"] = _json_bytes({name: hashlib.sha256(body).hexdigest() for name, body in files.items()})
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, body in files.items():
                entry = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                entry.compress_type = zipfile.ZIP_DEFLATED
                entry.external_attr = 0o100600 << 16
                archive.writestr(entry, body)
        content, mime, extension = buffer.getvalue(), "application/zip", "zip"
    else:
        raise DomainError("export_format_invalid", 422)
    if len(content) > MAX_EXPORT_BYTES:
        raise DomainError("export_too_large", 413)
    return content, mime, extension


def export_filename(title: str, extension: str) -> str:
    if extension not in {"txt", "md", "zip"}:
        raise DomainError("export_format_invalid", 422)
    stem = unicodedata.normalize("NFC", title)
    stem = "".join("-" if char in '<>:"/\\|?*' or unicodedata.category(char).startswith("C") else char for char in stem)
    stem = stem.strip(" .-")[:72].rstrip(" .")
    if not stem or stem in {".", ".."} or re.match(r"^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\.|$)", stem, re.I):
        stem = "作品"
    return f"{stem}-export.{extension}"


def register_project_export_routes(app: FastAPI, db: V2Database, user: Callable) -> None:
    @app.get("/api/projects/{project_id}/export")
    def download_project(request: Request, project_id: str, format: ExportFormat = "bundle", include_draft: bool = False):
        # There is deliberately no server path or user-supplied filename input.
        if set(request.query_params) - {"format", "include_draft"}:
            raise DomainError("export_parameters_invalid", 422)
        snapshot = project_snapshot(db, user(request)["id"], project_id, include_draft)
        content, mime, extension = export_content(snapshot, format)
        filename = export_filename(snapshot["project"]["title"], extension)
        return Response(content, media_type=mime, headers={
            "Content-Disposition": f"attachment; filename=\"story-export.{extension}\"; filename*=UTF-8''{quote(filename, safe='')}",
            "Cache-Control": "no-store, private",
            "X-Content-Type-Options": "nosniff",
            "X-Export-Snapshot-SHA256": snapshot["snapshot_sha256"],
        })

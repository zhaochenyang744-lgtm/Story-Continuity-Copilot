"""Word (.docx) import (v1.6.0).

Reads the paragraphs of word/document.xml into the Markdown the import parser already understands:
a paragraph styled as a level-1 or level-2 heading becomes a "# " chapter heading, every other
paragraph a plain line. Only the standard library is used. The archive and its XML are untrusted:
the uncompressed document is size-capped and a document type declaration (the vehicle for entity
expansion) is refused outright.
"""
from __future__ import annotations

import io
import re
import zipfile
from xml.etree import ElementTree as ET

from .database import DomainError

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
MAX_XML_BYTES = 30 * 1024 * 1024
HEADING_NAME = re.compile(r"^(?:heading|标题)\s*([1-9])$", re.IGNORECASE)


def _xml(archive: zipfile.ZipFile, name: str) -> ET.Element | None:
    try:
        info = archive.getinfo(name)
    except KeyError:
        return None
    if info.file_size > MAX_XML_BYTES:
        raise DomainError("import_too_large", 413)
    data = archive.read(info)
    if b"<!DOCTYPE" in data[:4096].upper():
        raise DomainError("unsupported_format", 415)
    try:
        return ET.fromstring(data)
    except ET.ParseError:
        raise DomainError("unsupported_format", 415) from None


def _heading_names(styles: ET.Element | None) -> dict[str, int]:
    """Style id -> heading level, from the style's name (Heading 1, 标题 1, ...)."""
    levels: dict[str, int] = {}
    if styles is None:
        return levels
    for style in styles.iter(W + "style"):
        name = style.find(W + "name")
        match = HEADING_NAME.match((name.get(W + "val") if name is not None else "") or "")
        style_id = style.get(W + "styleId")
        if match and style_id:
            levels[style_id] = int(match.group(1))
    return levels


def _paragraph_text(paragraph: ET.Element) -> str:
    parts: list[str] = []
    for node in paragraph.iter():
        if node.tag == W + "t" and node.text:
            parts.append(node.text)
        elif node.tag == W + "tab":
            parts.append("\t")
        elif node.tag in {W + "br", W + "cr"}:
            parts.append("\n")
    return "".join(parts)


def _heading_level(paragraph: ET.Element, levels: dict[str, int]) -> int | None:
    properties = paragraph.find(W + "pPr")
    if properties is None:
        return None
    outline = properties.find(W + "outlineLvl")
    if outline is not None and (outline.get(W + "val") or "").isdigit():
        return int(outline.get(W + "val")) + 1
    style = properties.find(W + "pStyle")
    return levels.get(style.get(W + "val") or "") if style is not None else None


def docx_to_markdown(content: bytes) -> str:
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise DomainError("unsupported_format", 415) from None
    with archive:
        document = _xml(archive, "word/document.xml")
        if document is None:
            raise DomainError("unsupported_format", 415)
        levels = _heading_names(_xml(archive, "word/styles.xml"))
    lines: list[str] = []
    body = document.find(W + "body")
    for paragraph in (body if body is not None else document).iter(W + "p"):
        text = _paragraph_text(paragraph).strip()
        level = _heading_level(paragraph, levels)
        if text and level is not None and level <= 2:
            lines.append("# " + " ".join(text.split()))
        else:
            lines.append(text)
    markdown = "\n".join(lines).strip()
    if not markdown:
        raise DomainError("empty_source", 422)
    return markdown + "\n"

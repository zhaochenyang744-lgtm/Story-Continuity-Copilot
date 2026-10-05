"""Word (.docx) import (v1.6.0): headings become chapters; the archive is treated as untrusted."""
from __future__ import annotations

import io
import pathlib
import tempfile
import unittest
import uuid
import zipfile

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.database import DomainError
from app.docx_import import docx_to_markdown
from app.main import create_app
from app.stage13 import Stage13Settings

NS = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
STYLES = f'''<?xml version="1.0" encoding="UTF-8"?><w:styles {NS}>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/></w:style>
<w:style w:type="paragraph" w:styleId="a3"><w:name w:val="标题 2"/></w:style>
<w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/></w:style></w:styles>'''


def paragraph(text: str, style: str | None = None) -> str:
    props = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    return f"<w:p>{props}<w:r><w:t>{text}</w:t></w:r></w:p>"


def docx(paragraphs: list[str], styles: str = STYLES, extra: dict[str, str] | None = None) -> bytes:
    document = f'<?xml version="1.0" encoding="UTF-8"?><w:document {NS}><w:body>{"".join(paragraphs)}</w:body></w:document>'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", document)
        archive.writestr("word/styles.xml", styles)
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
    return buffer.getvalue()


BOOK = docx([
    paragraph("第一章 雾钟", "Heading1"),
    paragraph("苏岑在黄昏时抵达灰港。"),
    paragraph("雾钟只在北潮闸关闭后敲响。"),
    paragraph("第二章 裂纹罗盘", "a3"),
    paragraph("她在测绘塔找到父亲的罗盘。"),
])


class DocxToMarkdownTests(unittest.TestCase):
    def test_headings_become_chapter_headings_and_paragraphs_lines(self):
        self.assertEqual(docx_to_markdown(BOOK).splitlines(),
                         ["# 第一章 雾钟", "苏岑在黄昏时抵达灰港。", "雾钟只在北潮闸关闭后敲响。", "# 第二章 裂纹罗盘", "她在测绘塔找到父亲的罗盘。"])

    def test_an_outline_level_marks_a_heading_without_a_named_style(self):
        outlined = '<w:p><w:pPr><w:outlineLvl w:val="0"/></w:pPr><w:r><w:t>序章</w:t></w:r></w:p>'
        self.assertEqual(docx_to_markdown(docx([outlined, paragraph("正文。")])).splitlines(), ["# 序章", "正文。"])

    def test_not_a_word_file_is_refused(self):
        for content in (b"plain text", docx([], extra={"other.xml": "<x/>"})[:20]):
            with self.assertRaises(DomainError) as caught:
                docx_to_markdown(content)
            self.assertEqual(caught.exception.code, "unsupported_format")

    def test_a_document_type_declaration_is_refused(self):
        bomb = f'<?xml version="1.0"?><!DOCTYPE lol [<!ENTITY a "aaaa">]><w:document {NS}><w:body>{paragraph("&a;")}</w:body></w:document>'
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("word/document.xml", bomb)
        with self.assertRaises(DomainError) as caught:
            docx_to_markdown(buffer.getvalue())
        self.assertEqual(caught.exception.code, "unsupported_format")

    def test_an_empty_document_is_refused(self):
        with self.assertRaises(DomainError) as caught:
            docx_to_markdown(docx([paragraph("")]))
        self.assertEqual(caught.exception.code, "empty_source")


class DocxImportApiTests(unittest.TestCase):
    def test_a_word_file_imports_by_its_headings(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix="v160-docx-"))
        app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"), settings=Stage13Settings.for_test())
        client = TestClient(app)
        self.addCleanup(client.close)
        client.post("/api/auth/register", headers={"Idempotency-Key": str(uuid.uuid4())}, json={
            "account_name": f"docx{uuid.uuid4().hex[:8]}", "display_name": "Docx", "password": "valid-password-99",
            "recovery_email": f"{uuid.uuid4().hex[:8]}@example.test"})
        preview = client.post("/api/imports/preview", headers={"Idempotency-Key": str(uuid.uuid4())},
                              files={"file": ("灰港.docx", BOOK, "application/vnd.openxmlformats-officedocument.wordprocessingml.document")})
        self.assertEqual(preview.status_code, 201, preview.text)
        data = preview.json()["data"]
        self.assertEqual(data["file"]["format"], "docx")
        self.assertEqual([item["title"] for item in data["detected"]["chapters"]], ["第一章 雾钟", "第二章 裂纹罗盘"])


if __name__ == "__main__":
    unittest.main()

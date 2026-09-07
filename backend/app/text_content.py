"""Content-format helpers shared by draft persistence and analysis.

Draft bodies remain losslessly stored in their authoring representation.  Only
the derived text sent to continuity/source-span consumers is projected to
visible text, so Markdown punctuation cannot become a story fact.
"""
from __future__ import annotations

import html
import re


DRAFT_BODY_FORMATS = {"plain_text", "markdown"}


def visible_draft_text(body: str, body_format: str) -> str:
    """Return reader-visible text for the Markdown subset emitted by Tiptap.

    The editor currently emits emphasis, block quote, unordered-list and hard
    break syntax. Escaped punctuation is protected before structural markers
    are removed, preserving literal asterisks and Windows-style paths.
    """
    if body_format != "markdown":
        return body

    protected: list[str] = []

    def protect(match: re.Match[str]) -> str:
        protected.append(match.group(1))
        return f"\ue000{len(protected) - 1}\ue001"

    value = html.unescape(body.replace("  \r\n", "\r\n").replace("  \n", "\n"))
    value = re.sub(r"\\([\\`*_[\]{}()#+\-.!>])", protect, value)
    lines: list[str] = []
    for line in value.splitlines():
        structural_only = bool(re.match(r"^\s*[-+*]\s*$", line))
        previous = None
        while previous != line:
            previous = line
            line = re.sub(r"^(?:\s*>\s*)+", "", line)
            line = re.sub(r"^\s*[-+*]\s+", "", line)
            line = re.sub(r"^\s*\d+[.)]\s+", "", line)
        line = re.sub(r"(?<!\\)(?:\*\*|__)(?=\S)|(?<=\S)(?:\*\*|__)", "", line)
        line = re.sub(r"(?<!\\)[*_](?=\S)|(?<=\S)[*_]", "", line)
        if not (structural_only and not line):
            lines.append(line)
    value = "\n".join(lines)
    for index, literal in enumerate(protected):
        value = value.replace(f"\ue000{index}\ue001", literal)
    return value

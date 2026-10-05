"""Remove internal record ids that a model copies into author-facing prose.

Analysis prompts hand the model evidence keyed by ids such as ``mem-<uuid>`` or
``draft-claim-draft-<uuid>-r1-4`` so it can cite sources structurally. Models
sometimes also write those ids into the answer text ("依据是第4章原文（span-…）"),
which authors cannot read. Citations stay in the structured evidence fields; only
the prose is cleaned.
"""

from __future__ import annotations

import re

_UUID = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_ID = (
    rf"(?:[a-z]+-)+{_UUID}(?:-[a-z0-9]+)*"  # prefixed uuid ids, incl. draft-claim-draft-<uuid>-r1-4
    r"|grey-harbor-[a-z]+(?:-[0-9a-z]+)+"  # tutorial seed ids
    r"|(?:mem|span|claim|draft-claim|ch|char|alias|plan|material|foreshadow|issue|ev|evidence)-[0-9a-f]{6,}[0-9a-z-]*"  # truncated ids
)
_SEPARATOR = r"\s*[，,、;；/和与及]\s*"
_BRACKETED_IDS = re.compile(rf"\s*[（(]\s*(?:(?:ID|id|编号)[:：]?\s*)?(?:{_ID})(?:{_SEPARATOR}(?:{_ID}))*\s*[）)]")
_BARE_ID = re.compile(rf"(?<![0-9A-Za-z-])(?:{_ID})(?![0-9A-Za-z-])")


def strip_internal_ids(text: str) -> str:
    """Drop bracketed id lists and bare ids, then tidy the punctuation they leave behind."""
    cleaned = _BRACKETED_IDS.sub("", text)
    cleaned = _BARE_ID.sub("", cleaned)
    cleaned = re.sub(r"[（(]\s*[）)]", "", cleaned)
    cleaned = re.sub(r"\s*([，。；：、！？）])", r"\1", cleaned)
    cleaned = re.sub(r"([，、；])\s*(?=[，。；、])", "", cleaned)
    cleaned = re.sub(r"[ \t]{2,}", " ", cleaned)
    return cleaned.strip()

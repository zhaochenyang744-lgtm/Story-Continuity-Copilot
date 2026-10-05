"""Shared 11I Memory-candidate vocabulary for live prompts and server classification."""

CONTROLLED_MEMORY_TYPES = frozenset({
    "static_canon",
    "dynamic_state",
    "event_timeline",
    "character_knowledge",
})

CONTROLLED_PREDICATES = (
    "identity",
    "relationship",
    "affiliation",
    "location",
    "status",
    "rule",
    "possession",
    "event_occurred",
    "knowledge",
)

# Author-facing wording for predicates, including legacy and seed spellings still stored in old
# projects. Labels only: prompts and stored records keep the keys.
PREDICATE_LABELS = {
    "identity": "身份",
    "relationship": "关系",
    "affiliation": "所属",
    "location": "所在位置",
    "status": "状态",
    "rule": "规则",
    "possession": "持有",
    "event_occurred": "发生的事件",
    "knowledge": "角色所知",
    "holder": "持有人 / 存放状态",
    "does_not_know": "尚未知晓",
    "next_action": "下一步行动",
    "ring_condition": "触发条件",
    "goal": "目标",
    "occurred_at": "发生时间",
    "time": "时间",
    "received": "接收记录",
}


def predicate_label(predicate: str) -> str:
    return PREDICATE_LABELS.get(str(predicate), "其他属性")


# Compatibility only: old persisted candidates may use these spellings. New
# live prompts receive CONTROLLED_PREDICATES and must not be taught aliases.
LEGACY_PREDICATE_ALIASES = {
    "knows": "knowledge",
    "permits": "rule",
    "signal": "rule",
    "kept_by": "possession",
}


def normalize_memory_value(value: str) -> str:
    return " ".join(value.casefold().split())


def normalized_predicate(predicate: str, *, allow_legacy_alias: bool = True) -> str:
    normalized = normalize_memory_value(predicate)
    return LEGACY_PREDICATE_ALIASES.get(normalized, normalized) if allow_legacy_alias else normalized


def is_controlled_candidate(
    memory_type: str,
    predicate: str,
    *,
    allow_legacy_alias: bool = True,
) -> bool:
    """Check the shared vocabulary, with aliases limited to legacy reads."""
    return (
        memory_type in CONTROLLED_MEMORY_TYPES
        and normalized_predicate(predicate, allow_legacy_alias=allow_legacy_alias)
        in CONTROLLED_PREDICATES
    )

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

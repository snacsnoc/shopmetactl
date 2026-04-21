from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

TYPE_PREFIX = "type:"


@dataclass(slots=True)
class SearchQuery:
    raw: str
    normalized: str
    namespace_pattern: str = "*"
    key_pattern: str = "*"
    text_filter: Optional[str] = None


def query_from_parts(namespace: Optional[str], key: Optional[str]) -> Optional[str]:
    if not namespace and not key:
        return None
    ns = namespace or "*"
    ks = key or "*"
    return f"{TYPE_PREFIX}{ns}.{ks}"


def normalize_query(raw: str) -> str:
    # Expands namespace.key, .key, and type:namespace inputs into Shopify's type filter syntax
    text = raw.strip()
    if not text:
        return ""

    lowered = text.lower()
    if lowered.startswith(TYPE_PREFIX):
        value = text[len(TYPE_PREFIX) :].strip()
        return _normalize_type_value(value)

    if "." in text and " " not in text:
        namespace, key = text.split(".", 1)
        return query_from_parts(namespace or None, key or None) or text

    if text.startswith("."):
        return query_from_parts(None, text[1:] or None) or text

    return text


def parse_search_query(raw: str, *, type_only: bool = False) -> SearchQuery:
    text = raw.strip()
    namespace_pattern, key_pattern = "*", "*"
    text_filter: Optional[str] = None
    normalized = text

    is_type_query = type_only or text.lower().startswith(TYPE_PREFIX)
    if is_type_query:
        normalized = normalize_query(text)
    else:
        normalized = text

    if normalized.startswith(TYPE_PREFIX):
        type_value = normalized[len(TYPE_PREFIX) :].lower()
        if "." in type_value:
            namespace_pattern, key_pattern = type_value.split(".", 1)
        else:
            namespace_pattern = type_value or "*"
            key_pattern = "*"
    elif normalized:
        text_filter = normalized or None

    return SearchQuery(
        raw=raw,
        normalized=normalized,
        namespace_pattern=namespace_pattern or "*",
        key_pattern=key_pattern or "*",
        text_filter=text_filter,
    )


def _normalize_type_value(value: str) -> str:
    if not value:
        return f"{TYPE_PREFIX}*.*"

    if "." not in value and not value.endswith("*"):
        return f"{TYPE_PREFIX}{value}.*"

    if value.startswith("."):
        key = value[1:] or "*"
        return f"{TYPE_PREFIX}*.{key}"

    if value.endswith("."):
        return f"{TYPE_PREFIX}{value}*"

    return f"{TYPE_PREFIX}{value}"

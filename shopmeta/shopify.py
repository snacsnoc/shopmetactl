from __future__ import annotations

import json
from dataclasses import dataclass, field
from fnmatch import fnmatchcase
from typing import Any, Dict, List, Optional

import requests

from .config import Config
from .search import SearchQuery


class ShopifyAPIError(RuntimeError):
    pass


@dataclass(slots=True)
class ShopifyClient:
    config: Config
    endpoint: str = field(init=False)
    session: requests.Session = field(init=False, repr=False)

    def __post_init__(self) -> None:
        self.endpoint = (
            f"https://{self.config.sanitized_domain}/admin/api/"
            f"{self.config.api_version}/graphql.json"
        )
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Content-Type": "application/json",
                "X-Shopify-Access-Token": self.config.access_token,
            }
        )

    def query(
        self, query: str, variables: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        payload = {"query": query, "variables": variables or {}}
        response = self.session.post(self.endpoint, json=payload, timeout=30)
        if response.status_code >= 400:
            raise ShopifyAPIError(f"HTTP {response.status_code}: {response.text}")

        try:
            data = response.json()
        except json.JSONDecodeError as exc:
            raise ShopifyAPIError(
                f"Invalid JSON response (HTTP {response.status_code}): {response.text[:200]}"
            ) from exc
        errors = data.get("errors")
        if errors:
            raise ShopifyAPIError(json.dumps(errors, indent=2))
        return data["data"]

    def fetch_metaobject_tree(
        self, limit_types: int = 10, limit_entries: int = 5
    ) -> List[Dict[str, Any]]:
        data = self.query(
            METAOBJECT_TREE_QUERY,
            {"first": limit_types, "entries": limit_entries},
        )
        return data["metaobjectDefinitions"]["nodes"]

    def fetch_metaobject_definition(
        self, type_name: str, limit_entries: int = 10
    ) -> Optional[Dict[str, Any]]:
        result = self.query(
            METAOBJECT_DEFINITION_QUERY,
            {"type": type_name, "entries": limit_entries},
        )
        return result.get("metaobjectDefinitionByType")

    def search_metaobjects(
        self, query_data: SearchQuery, limit: int = 20
    ) -> List[Dict[str, Any]]:
        matches = self._find_definition_matches(
            query_data.namespace_pattern, query_data.key_pattern
        )
        results: List[Dict[str, Any]] = []
        text_filter = (query_data.text_filter or "").lower()
        for definition in matches:
            if len(results) >= limit:
                break
            remaining = limit - len(results)
            detail = self.fetch_metaobject_definition(definition["type"], remaining)
            if not detail:
                continue
            entries = detail.get("metaobjects", {}).get("nodes", [])
            for entry in entries:
                if len(results) >= limit:
                    break
                if text_filter and not self._entry_matches_filter(entry, text_filter):
                    continue
                enriched = dict(entry)
                enriched.setdefault(
                    "definition",
                    {"name": detail.get("name"), "type": detail.get("type")},
                )
                enriched.setdefault("type", detail.get("type"))
                results.append(enriched)
        return results

    def _find_definition_matches(
        self, namespace_pattern: str, key_pattern: str, *, batch_size: int = 50
    ) -> List[Dict[str, Any]]:
        matches: List[Dict[str, Any]] = []
        after: Optional[str] = None
        while True:
            data = self.query(
                METAOBJECT_DEFINITION_LIST_QUERY,
                {"first": batch_size, "after": after},
            )
            connection = data["metaobjectDefinitions"]
            for node in connection["nodes"]:
                type_value = node.get("type", "")
                if "." in type_value:
                    namespace, key = type_value.split(".", 1)
                else:
                    namespace, key = type_value, ""
                if fnmatchcase(namespace or "", namespace_pattern) and fnmatchcase(
                    key or "", key_pattern
                ):
                    matches.append(node)
            page_info = connection["pageInfo"]
            if not page_info["hasNextPage"]:
                break
            after = page_info.get("endCursor")
            if not after:
                break
        return matches

    @staticmethod
    def _entry_matches_filter(entry: Dict[str, Any], needle: str) -> bool:
        haystacks = [
            entry.get("displayName", "") or "",
            entry.get("handle", "") or "",
            entry.get("updatedAt", "") or "",
        ]
        for field in entry.get("fields", []):
            haystacks.append(field.get("value") or "")
            haystacks.append(field.get("key") or "")
        for value in haystacks:
            if needle in (value or "").lower():
                return True
        return False


# TODO: put these queries somewhere better
METAOBJECT_TREE_QUERY = """
query MetaobjectDefinitions($first: Int!, $entries: Int!) {
  metaobjectDefinitions(first: $first) {
    nodes {
      id
      name
      type
      fieldDefinitions {
        name
        key
        type {
          name
        }
        description
      }
      metaobjects(first: $entries) {
        nodes {
          id
          type
          definition {
            name
            type
          }
          displayName
          handle
          updatedAt
          fields {
            key
            value
          }
        }
        pageInfo {
          hasNextPage
        }
      }
    }
  }
}
"""

METAOBJECT_DEFINITION_QUERY = """
query MetaobjectDefinitionByType($type: String!, $entries: Int!) {
  metaobjectDefinitionByType(type: $type) {
    id
    name
    type
    fieldDefinitions {
      name
      key
      type {
        name
      }
      description
    }
    metaobjects(first: $entries) {
      nodes {
        id
        displayName
        handle
        updatedAt
        fields {
          key
          value
        }
      }
      pageInfo {
        hasNextPage
      }
    }
  }
}
"""

METAOBJECT_DEFINITION_LIST_QUERY = """
query DefinitionList($first: Int!, $after: String) {
  metaobjectDefinitions(first: $first, after: $after) {
    nodes {
      id
      name
      type
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path
from typing import Optional

from urllib.parse import urlparse

from pydantic import BaseModel, Field, ValidationError

DEFAULT_API_VERSION = "2025-10"
CONFIG_DIR = Path(os.environ.get("SHOPMETA_HOME", Path.home() / ".shopmeta"))
CONFIG_PATH = CONFIG_DIR / "config.json"


class Config(BaseModel):
    store_domain: str = Field(..., description="my-store.myshopify.com")
    access_token: str = Field(..., description="Admin API access token")
    api_version: str = Field(
        DEFAULT_API_VERSION, description="Shopify Admin API version"
    )

    @property
    def sanitized_domain(self) -> str:
        return sanitize_store_domain(self.store_domain)


def sanitize_store_domain(domain: str) -> str:
    parsed = urlparse(domain if "://" in domain else f"https://{domain}")
    host = parsed.netloc or parsed.path
    cleaned = host.split("@")[-1].split(":")[0].strip("/")
    if not cleaned.endswith(".myshopify.com"):
        cleaned = f"{cleaned}.myshopify.com"
    return cleaned


def load_config() -> Optional[Config]:
    env_store = os.environ.get("SHOPMETA_STORE")
    env_token = os.environ.get("SHOPMETA_TOKEN")
    env_version = os.environ.get("SHOPMETA_API_VERSION", DEFAULT_API_VERSION)

    if env_store and env_token:
        return Config(
            store_domain=env_store, access_token=env_token, api_version=env_version
        )

    if not CONFIG_PATH.exists():
        return None

    content = CONFIG_PATH.read_text(encoding="utf-8")
    try:
        data = json.loads(content)
        return Config(**data)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise RuntimeError(
            f"Config at {CONFIG_PATH} is invalid. Delete it or fix the JSON"
        ) from exc


def save_config(config: Config) -> Path:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_DIR.chmod(0o700)
    CONFIG_PATH.write_text(config.model_dump_json(indent=2), encoding="utf-8")
    CONFIG_PATH.chmod(0o600)
    return CONFIG_PATH

"""Shared accessors for the `connectors` block in `config/query_registry.json`.

Both discovery and harvest read the same registry to decide whether to call a
given upstream API. Centralising the lookup here keeps the gating policy in
one place — if discovery skips Semantic Scholar (no API key, free public tier
429s on every call), harvest's per-candidate fallback should skip it too.
"""
from __future__ import annotations
from typing import Any
from alex.utils.io import load_json, root_file


def load() -> dict:
    return load_json(root_file("config", "query_registry.json"))


def is_enabled(config: dict, name: str, default: bool = True) -> bool:
    block = (config.get("connectors") or {}).get(name) or {}
    return bool(block.get("enabled", default))


def setting(config: dict, name: str, key: str, default: Any = None) -> Any:
    block = (config.get("connectors") or {}).get(name) or {}
    return block.get(key, default)

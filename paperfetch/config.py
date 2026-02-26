from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class AppConfig:
    llm_base_url: str
    llm_api_key: str
    llm_model: str
    llm_disable_reasoning: bool
    llm_system_prompt: str
    s2_api_key: str
    openalex_email: str
    source_path: str


def _to_str(value: Any) -> str:
    return str(value or "").strip()


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return _to_str(value).lower() in {"1", "true", "yes", "on"}


def _pick_config_path() -> Path | None:
    configured = _to_str(os.getenv("PAPERFETCH_CONFIG_FILE"))
    if configured:
        path = Path(configured)
        if not path.exists():
            raise RuntimeError(f"Config file not found: {path}")
        return path

    default_paths = [Path("config.local.json")]
    for path in default_paths:
        if path.exists():
            return path
    return None


def _load_json_object(path: Path) -> dict[str, Any]:
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RuntimeError(f"Failed to read config file: {path}") from error
    if not isinstance(loaded, dict):
        raise RuntimeError(f"Config file must be a JSON object: {path}")
    return loaded


def _deep_merge_dict(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged: dict[str, Any] = dict(base)
    for key, override_value in override.items():
        base_value = merged.get(key)
        if isinstance(base_value, dict) and isinstance(override_value, dict):
            merged[key] = _deep_merge_dict(base_value, override_value)
        else:
            merged[key] = override_value
    return merged


def _clear_placeholder(value: Any) -> str:
    text = _to_str(value)
    if text in {"YOUR_LLM_API_KEY", "YOUR_S2_API_KEY", "you@example.com"}:
        return ""
    return text


def load_app_config() -> AppConfig:
    config_path = _pick_config_path()
    default_path = Path("config.example.json")
    default_raw: dict[str, Any] = _load_json_object(default_path) if default_path.exists() else {}
    override_raw: dict[str, Any] = _load_json_object(config_path) if config_path is not None else {}
    raw: dict[str, Any] = _deep_merge_dict(default_raw, override_raw)

    llm_obj = raw.get("llm") if isinstance(raw.get("llm"), dict) else {}
    providers_obj = raw.get("providers") if isinstance(raw.get("providers"), dict) else {}

    llm_base_url = _clear_placeholder(llm_obj.get("base_url") or raw.get("base_url"))
    llm_api_key = _clear_placeholder(llm_obj.get("api_key") or raw.get("api_key"))
    llm_model = _clear_placeholder(llm_obj.get("model") or raw.get("model"))
    llm_disable_reasoning = _to_bool(
        llm_obj.get("disable_reasoning")
        if isinstance(llm_obj, dict) and "disable_reasoning" in llm_obj
        else raw.get("disable_reasoning")
    )
    llm_system_prompt = _clear_placeholder(llm_obj.get("system_prompt") or raw.get("system_prompt"))

    s2_api_key = _clear_placeholder(
        providers_obj.get("s2_api_key")
        if isinstance(providers_obj, dict) and "s2_api_key" in providers_obj
        else raw.get("s2_api_key")
    )
    openalex_email = _clear_placeholder(
        providers_obj.get("openalex_email")
        if isinstance(providers_obj, dict) and "openalex_email" in providers_obj
        else raw.get("openalex_email")
    )

    source_parts: list[str] = []
    if default_path.exists():
        source_parts.append(str(default_path))
    if config_path is not None:
        source_parts.append(str(config_path))
    source_path = " + ".join(source_parts) if source_parts else "config.local.json"

    return AppConfig(
        llm_base_url=llm_base_url,
        llm_api_key=llm_api_key,
        llm_model=llm_model,
        llm_disable_reasoning=llm_disable_reasoning,
        llm_system_prompt=llm_system_prompt,
        s2_api_key=s2_api_key,
        openalex_email=openalex_email,
        source_path=source_path,
    )

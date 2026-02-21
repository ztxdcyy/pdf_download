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


def load_app_config() -> AppConfig:
    config_path = _pick_config_path()
    raw: dict[str, Any] = {}

    if config_path is not None:
        try:
            loaded = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise RuntimeError(f"Failed to read config file: {config_path}") from error
        if not isinstance(loaded, dict):
            raise RuntimeError(f"Config file must be a JSON object: {config_path}")
        raw = loaded

    llm_obj = raw.get("llm") if isinstance(raw.get("llm"), dict) else {}
    providers_obj = raw.get("providers") if isinstance(raw.get("providers"), dict) else {}

    llm_base_url = _to_str(llm_obj.get("base_url") or raw.get("base_url"))
    llm_api_key = _to_str(llm_obj.get("api_key") or raw.get("api_key"))
    llm_model = _to_str(llm_obj.get("model") or raw.get("model"))
    llm_disable_reasoning = _to_bool(
        llm_obj.get("disable_reasoning")
        if isinstance(llm_obj, dict) and "disable_reasoning" in llm_obj
        else raw.get("disable_reasoning")
    )

    s2_api_key = _to_str(
        providers_obj.get("s2_api_key")
        if isinstance(providers_obj, dict) and "s2_api_key" in providers_obj
        else raw.get("s2_api_key")
    )
    openalex_email = _to_str(
        providers_obj.get("openalex_email")
        if isinstance(providers_obj, dict) and "openalex_email" in providers_obj
        else raw.get("openalex_email")
    )

    return AppConfig(
        llm_base_url=llm_base_url,
        llm_api_key=llm_api_key,
        llm_model=llm_model,
        llm_disable_reasoning=llm_disable_reasoning,
        s2_api_key=s2_api_key,
        openalex_email=openalex_email,
        source_path=str(config_path or "config.local.json"),
    )

from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from typing import Any

import requests

from paperfetch.config import AppConfig


@dataclass(frozen=True)
class LLMClientConfig:
    base_url: str
    api_key: str
    model: str
    timeout: float = 30.0
    disable_reasoning: bool = False
    system_prompt: str = ""


@dataclass(frozen=True)
class TitleProposal:
    titles: list[str]
    reason: str
    confidence: float


class LLMTitleError(RuntimeError):
    """Raised when LLM title proposal fails."""


def _is_debug_enabled() -> bool:
    import os

    value = (os.getenv("LLM_DEBUG") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _debug_log(message: str) -> None:
    if _is_debug_enabled():
        print(f"[llm-title-debug] {message}", file=sys.stderr)


def load_llm_config(timeout: float, app_config: AppConfig) -> LLMClientConfig:
    base_url = app_config.llm_base_url
    api_key = app_config.llm_api_key
    model = app_config.llm_model
    disable_reasoning = app_config.llm_disable_reasoning
    system_prompt = app_config.llm_system_prompt

    missing = [
        name
        for name, value in (
            ("llm.base_url", base_url),
            ("llm.api_key", api_key),
            ("llm.model", model),
        )
        if not value
    ]
    if missing:
        raise LLMTitleError(
            f"Missing LLM config in {app_config.source_path}: {', '.join(missing)}."
        )
    if not base_url.startswith("http"):
        raise LLMTitleError("llm.base_url must start with http/https.")
    if timeout <= 0:
        raise LLMTitleError("LLM timeout must be > 0.")

    return LLMClientConfig(
        base_url=base_url,
        api_key=api_key,
        model=model,
        timeout=timeout,
        disable_reasoning=disable_reasoning,
        system_prompt=system_prompt,
    )


def _extract_content(response_json: dict[str, Any]) -> str:
    choices = response_json.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMTitleError("LLM response has no choices.")

    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first, dict) else {}
    if not isinstance(message, dict):
        raise LLMTitleError("LLM response choice has no message.")

    content = message.get("content")
    if isinstance(content, str) and content.strip():
        return content.strip()

    # Fallback: some models return non-empty reasoning content when content is empty.
    reasoning_content = message.get("reasoning_content")
    if isinstance(reasoning_content, str) and reasoning_content.strip():
        return reasoning_content.strip()

    raise LLMTitleError("LLM response content is empty.")


def _extract_json(raw_text: str) -> dict[str, Any]:
    text = (raw_text or "").strip()
    if not text:
        raise LLMTitleError("LLM returned empty text.")
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    parsed_candidates: list[dict[str, Any]] = []
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            parsed_candidates.append(parsed)

    if not parsed_candidates:
        raise LLMTitleError("LLM text does not contain JSON object.")

    for parsed in parsed_candidates:
        if "titles" in parsed:
            return parsed
    return parsed_candidates[0]


def _normalize_titles(value: Any) -> list[str]:
    if not isinstance(value, list):
        raise LLMTitleError("LLM titles must be a JSON array.")
    titles: list[str] = []
    seen: set[str] = set()
    for item in value:
        text = str(item or "").strip()
        if not text:
            continue
        normalized = re.sub(r"\s+", " ", text)
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        titles.append(normalized)
    if not titles:
        raise LLMTitleError("LLM returned empty titles list.")
    return titles[:3]


def _looks_like_paper_title(text: str) -> bool:
    candidate = re.sub(r"\s+", " ", text).strip()
    if len(candidate) < 12 or len(candidate) > 240:
        return False
    if len(candidate.split()) < 3:
        return False
    lowered = candidate.lower()
    banned = {
        "keyword",
        "output format",
        "schema",
        "constraints",
        "json",
        "confidence",
        "reason",
    }
    return not any(token in lowered for token in banned)


def _extract_titles_from_text_fallback(text: str) -> list[str]:
    quoted = re.findall(r"\"([^\"]{6,260})\"", text)
    single_quoted = re.findall(r"'([^']{6,260})'", text)
    titled_fragments = re.findall(r"titled\s+([A-Z][^.:\n]{8,260})", text, flags=re.IGNORECASE)
    candidates = quoted + single_quoted + titled_fragments

    titles: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        normalized = re.sub(r"\s+", " ", item).strip(" .,:;")
        if not _looks_like_paper_title(normalized):
            continue
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        titles.append(normalized)
    return titles[:3]


def _extract_reasoning_text(response_json: dict[str, Any]) -> str:
    choices = response_json.get("choices")
    if not isinstance(choices, list) or not choices:
        return ""
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first, dict) else {}
    if not isinstance(message, dict):
        return ""
    reasoning = message.get("reasoning_content")
    return reasoning.strip() if isinstance(reasoning, str) else ""


def _fallback_proposal_from_reasoning(response_json: dict[str, Any]) -> TitleProposal | None:
    reasoning = _extract_reasoning_text(response_json)
    if not reasoning:
        return None
    titles = _extract_titles_from_text_fallback(reasoning)
    if not titles:
        return None
    return TitleProposal(
        titles=titles,
        reason="LLM JSON output was truncated; extracted candidate titles from reasoning content.",
        confidence=0.35,
    )


def _validate_payload(payload: dict[str, Any]) -> TitleProposal:
    titles = _normalize_titles(payload.get("titles"))
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise LLMTitleError("LLM reason is empty.")

    confidence_raw = payload.get("confidence")
    try:
        confidence = float(confidence_raw)
    except (TypeError, ValueError) as error:
        raise LLMTitleError("LLM confidence is missing or invalid.") from error
    if confidence < 0.0 or confidence > 1.0:
        raise LLMTitleError("LLM confidence must be in [0, 1].")

    return TitleProposal(titles=titles, reason=reason, confidence=confidence)


def _compose_system_prompt(default_prompt: str, user_prompt: str) -> str:
    custom = str(user_prompt or "").strip()
    if not custom:
        return default_prompt
    return (
        f"{default_prompt}\n\n"
        "Additional user preference (higher priority unless it conflicts with JSON constraints):\n"
        f"{custom}"
    )


def _build_messages(keyword: str, user_system_prompt: str) -> list[dict[str, str]]:
    default_system_prompt = (
        "Given a keyword, propose likely original/seminal paper titles. "
        "Return strict JSON only."
    )
    system_prompt = _compose_system_prompt(default_system_prompt, user_system_prompt)
    user_payload = {
        "keyword": keyword,
        "output_schema": {
            "titles": ["string", "string", "string"],
            "reason": "1-2 sentences",
            "confidence": "0~1 number",
        },
        "constraints": [
            "titles must be specific paper titles",
            "prefer original/first paper over later variants",
            "no markdown, return JSON only",
        ],
    }
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]


def propose_titles(keyword: str, client_cfg: LLMClientConfig) -> TitleProposal:
    if not str(keyword or "").strip():
        raise LLMTitleError("Keyword is empty.")

    endpoint = client_cfg.base_url.rstrip("/") + "/chat/completions"
    request_payload = {
        "model": client_cfg.model,
        "temperature": 0,
        "max_tokens": 512,
        "messages": _build_messages(keyword, client_cfg.system_prompt),
    }
    if client_cfg.disable_reasoning:
        request_payload["thinking"] = {"type": "disabled"}
    headers = {
        "Authorization": f"Bearer {client_cfg.api_key}",
        "Content-Type": "application/json",
    }
    try:
        _debug_log(
            f"POST {endpoint} model={client_cfg.model} timeout={client_cfg.timeout} "
            f"payload_chars={len(json.dumps(request_payload, ensure_ascii=False))}"
        )
        response = requests.post(
            endpoint,
            json=request_payload,
            headers=headers,
            timeout=(10, client_cfg.timeout),
        )
    except requests.Timeout as error:
        raise LLMTitleError("LLM title request timed out.") from error
    except requests.RequestException as error:
        raise LLMTitleError(f"LLM title request failed before response: {error}") from error

    if response.status_code >= 400 and client_cfg.disable_reasoning:
        # Some providers may not support the `thinking` field; retry once without it.
        retry_payload = dict(request_payload)
        retry_payload.pop("thinking", None)
        _debug_log("disable_reasoning request got HTTP>=400, retrying without thinking field.")
        try:
            response = requests.post(
                endpoint,
                json=retry_payload,
                headers=headers,
                timeout=(10, client_cfg.timeout),
            )
        except requests.Timeout as error:
            raise LLMTitleError("LLM title retry timed out.") from error
        except requests.RequestException as error:
            raise LLMTitleError(f"LLM title retry failed before response: {error}") from error

    if response.status_code >= 400:
        raise LLMTitleError(f"LLM title request failed: HTTP {response.status_code} {response.text[:300]}")
    _debug_log(f"status={response.status_code} raw_preview={response.text[:800]}")

    try:
        response_json = response.json()
    except ValueError as error:
        raise LLMTitleError("LLM title response is not valid JSON.") from error

    try:
        content = _extract_content(response_json)
        parsed = _extract_json(content)
        return _validate_payload(parsed)
    except LLMTitleError as first_error:
        fallback = _fallback_proposal_from_reasoning(response_json)
        if fallback is not None:
            _debug_log("Using fallback title extraction from reasoning_content.")
            return fallback
        raise first_error

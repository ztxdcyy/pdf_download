from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any

import requests

from paperfetch.title_llm import LLMClientConfig


@dataclass(frozen=True)
class PoolSelection:
    candidate_id: str
    reason: str
    confidence: float


class LLMPoolError(RuntimeError):
    """Raised when LLM pool selection fails."""


def _is_debug_enabled() -> bool:
    import os

    value = (os.getenv("LLM_DEBUG") or "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def _debug_log(message: str) -> None:
    if _is_debug_enabled():
        print(f"[llm-pool-debug] {message}", file=sys.stderr)


def _extract_json(raw_text: str) -> dict[str, Any]:
    text = (raw_text or "").strip()
    if not text:
        raise LLMPoolError("LLM returned empty text.")
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(text[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise LLMPoolError("LLM text does not contain JSON object.")


def _validate_payload(payload: dict[str, Any]) -> PoolSelection:
    candidate_id = str(payload.get("selected_candidate_id") or "").strip()
    if not candidate_id:
        raise LLMPoolError("LLM selected_candidate_id is empty.")
    reason = str(payload.get("reason") or "").strip()
    if not reason:
        raise LLMPoolError("LLM reason is empty.")
    try:
        confidence = float(payload.get("confidence"))
    except (TypeError, ValueError) as error:
        raise LLMPoolError("LLM confidence is missing or invalid.") from error
    if confidence < 0.0 or confidence > 1.0:
        raise LLMPoolError("LLM confidence must be in [0, 1].")
    return PoolSelection(candidate_id=candidate_id, reason=reason, confidence=confidence)


def _build_messages(
    keyword: str,
    proposed_titles: list[str],
    candidates: list[dict[str, Any]],
    user_system_prompt: str,
) -> list[dict[str, str]]:
    default_system_prompt = (
        "Select the most likely original/seminal paper from candidates. "
        "Return strict JSON only."
    )
    custom = str(user_system_prompt or "").strip()
    if custom:
        system_prompt = (
            f"{default_system_prompt}\n\n"
            "Additional user preference (higher priority unless it conflicts with JSON constraints):\n"
            f"{custom}"
        )
    else:
        system_prompt = default_system_prompt
    simplified_candidates = []
    for candidate in candidates:
        simplified_candidates.append(
            {
                "candidate_id": candidate.get("candidate_id"),
                "title": candidate.get("title"),
                "year": candidate.get("year"),
                "venue": candidate.get("venue"),
                "doi": candidate.get("doi"),
                "citationCount": candidate.get("citationCount"),
                "abstract": candidate.get("abstract"),
                "url": candidate.get("url"),
            }
        )
    user_payload = {
        "keyword": keyword,
        "proposed_titles": proposed_titles,
        "candidates": simplified_candidates,
        "output_schema": {
            "selected_candidate_id": "string (must be one of candidate_id)",
            "reason": "1-2 sentences",
            "confidence": "0~1 number",
        },
        "constraints": [
            "prefer the original/first paper",
            "avoid obvious variants or improvements",
            "return JSON only, no markdown",
        ],
    }
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": json.dumps(user_payload, ensure_ascii=False)},
    ]


def select_from_pool(
    keyword: str,
    proposed_titles: list[str],
    candidates: list[dict[str, Any]],
    client_cfg: LLMClientConfig,
) -> PoolSelection:
    if not candidates:
        raise LLMPoolError("No candidates provided for pool selection.")
    if not proposed_titles:
        raise LLMPoolError("No proposed titles provided for pool selection.")

    endpoint = client_cfg.base_url.rstrip("/") + "/chat/completions"
    payload = {
        "model": client_cfg.model,
        "temperature": 0,
        "max_tokens": 512,
        "messages": _build_messages(keyword, proposed_titles, candidates, client_cfg.system_prompt),
    }
    if client_cfg.disable_reasoning:
        payload["thinking"] = {"type": "disabled"}
    headers = {
        "Authorization": f"Bearer {client_cfg.api_key}",
        "Content-Type": "application/json",
    }
    try:
        _debug_log(
            f"POST {endpoint} model={client_cfg.model} timeout={client_cfg.timeout} "
            f"payload_chars={len(json.dumps(payload, ensure_ascii=False))}"
        )
        response = requests.post(
            endpoint,
            json=payload,
            headers=headers,
            timeout=(10, client_cfg.timeout),
        )
    except requests.Timeout as error:
        raise LLMPoolError("LLM pool request timed out.") from error
    except requests.RequestException as error:
        raise LLMPoolError(f"LLM pool request failed before response: {error}") from error

    if response.status_code >= 400 and client_cfg.disable_reasoning:
        retry_payload = dict(payload)
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
            raise LLMPoolError("LLM pool retry timed out.") from error
        except requests.RequestException as error:
            raise LLMPoolError(f"LLM pool retry failed before response: {error}") from error

    if response.status_code >= 400:
        raise LLMPoolError(f"LLM pool request failed: HTTP {response.status_code} {response.text[:300]}")
    _debug_log(f"status={response.status_code} raw_preview={response.text[:800]}")

    try:
        response_json = response.json()
    except ValueError as error:
        raise LLMPoolError("LLM pool response is not valid JSON.") from error

    choices = response_json.get("choices")
    if not isinstance(choices, list) or not choices:
        raise LLMPoolError("LLM pool response has no choices.")
    first = choices[0] if isinstance(choices[0], dict) else {}
    message = first.get("message") if isinstance(first, dict) else {}
    if not isinstance(message, dict):
        raise LLMPoolError("LLM pool response choice has no message.")
    content = message.get("content")
    if not isinstance(content, str) or not content.strip():
        raise LLMPoolError("LLM pool response content is empty.")

    parsed = _extract_json(content)
    return _validate_payload(parsed)

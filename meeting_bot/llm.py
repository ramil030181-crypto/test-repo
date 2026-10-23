# -*- coding: utf-8 -*-
"""Обращение к модели: стенограмма → Protocol (JSON по схеме).

Три варианта (LLM_BACKEND в .env):
  claude  — Claude по API (ключ с console.anthropic.com, оплата за запросы, не подписка);
  ollama  — локальная модель Ollama (данные не уходят из сети предприятия);
  fixture — готовый ответ из файла, для репетиции без интернета и ключей.
"""
import json
import logging
import os
from pathlib import Path

from meeting import Directory, Meeting, calendar_hint
from schema import Protocol

log = logging.getLogger(__name__)
HERE = Path(__file__).parent


class LLMError(RuntimeError):
    pass


def build_messages(meeting: Meeting, directory: Directory) -> tuple[str, str]:
    system = (HERE / "prompt_protocol.txt").read_text(encoding="utf-8")
    user = (
        f"ДАТА И КАЛЕНДАРЬ\n{calendar_hint(meeting.date)}\n\n"
        f"СПРАВОЧНИК УЧАСТНИКОВ ({directory.data.get('organization', '')})\n{directory.describe()}\n\n"
        f"СЛОВАРЬ ОБОЗНАЧЕНИЙ\n{directory.glossary}\n\n"
        f"СТЕНОГРАММА\n<transcript>\n{meeting.transcript()}\n</transcript>\n\n"
        "Составь протокол строго по правилам. Верни JSON по заданной схеме."
    )
    return system, user


def make_protocol(meeting: Meeting, directory: Directory) -> Protocol:
    backend = os.getenv("LLM_BACKEND", "claude").lower()
    system, user = build_messages(meeting, directory)
    if backend == "claude":
        return _claude(system, user)
    if backend == "ollama":
        return _ollama(system, user)
    if backend == "fixture":
        path = os.getenv("LLM_FIXTURE") or str(HERE / "tests" / "fixture_protocol_2026-11-23.json")
        return Protocol.model_validate_json(Path(path).read_text(encoding="utf-8"))
    raise LLMError(f"Неизвестный LLM_BACKEND={backend!r}: нужен claude, ollama или fixture")


def _claude(system: str, user: str) -> Protocol:
    import anthropic

    client = anthropic.Anthropic()  # ключ берётся из ANTHROPIC_API_KEY
    try:
        # fallbacks="default": если модель откажется отвечать, API сам повторит запрос на запасной модели
        resp = client.beta.messages.parse(
            model=os.getenv("CLAUDE_MODEL", "claude-opus-5-5"),
            max_tokens=16000,
            system=system,
            messages=[{"role": "user", "content": user}],
            output_format=Protocol,
            output_config={"effort": os.getenv("CLAUDE_EFFORT", "medium")},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
    except anthropic.AuthenticationError as e:
        raise LLMError("Claude API не принял ключ: проверьте ANTHROPIC_API_KEY в .env") from e
    except anthropic.RateLimitError as e:
        raise LLMError("Claude API: превышен лимит запросов, повторите через минуту") from e
    except anthropic.APIStatusError as e:
        raise LLMError(f"Claude API вернул ошибку {e.status_code}: {e.message}") from e
    except anthropic.APIConnectionError as e:
        raise LLMError("Нет связи с Claude API: проверьте интернет или прокси") from e
    if resp.stop_reason == "refusal":
        raise LLMError("Модель отказалась обрабатывать стенограмму")
    if resp.stop_reason == "max_tokens":
        raise LLMError("Ответ модели обрезан по длине: стенограмма слишком длинная")
    if resp.parsed_output is None:
        raise LLMError("Модель вернула ответ не по схеме")
    u = resp.usage
    log.info("Claude: модель %s, токены вход %s / выход %s", resp.model, u.input_tokens, u.output_tokens)
    return resp.parsed_output


def _ollama(system: str, user: str) -> Protocol:
    import httpx

    url = os.getenv("OLLAMA_URL", "http://localhost:11434").rstrip("/") + "/api/chat"
    body = {
        "model": os.getenv("OLLAMA_MODEL", "qwen2.5:14b"),
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        "format": Protocol.model_json_schema(),  # Ollama умеет ограничивать ответ JSON-схемой
        "stream": False,
        "options": {"temperature": 0, "num_ctx": 16384},
    }
    try:
        r = httpx.post(url, json=body, timeout=900)
        r.raise_for_status()
    except httpx.HTTPError as e:
        raise LLMError(f"Ollama недоступна по адресу {url}: {e}") from e
    content = r.json()["message"]["content"]
    try:
        return Protocol.model_validate(json.loads(content))
    except Exception as e:  # локальные модели иногда ломают JSON
        raise LLMError("Локальная модель вернула ответ не по схеме — попробуйте модель крупнее") from e

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

from .languages import label_from_code
from .srt import SubtitleCue

DEFAULT_TRANSLATION_BASE_URL = "https://api.openai.com/v1"
DEFAULT_TRANSLATION_MODEL = "gpt-4o-mini"


@dataclass(frozen=True)
class AITranslationOptions:
    source_language: str
    target_language: str
    api_key: str = ""
    model: str = DEFAULT_TRANSLATION_MODEL
    base_url: str = DEFAULT_TRANSLATION_BASE_URL
    batch_size: int = 20


ChatClient = Callable[[list[dict[str, str]], AITranslationOptions], str]


def default_translation_model() -> str:
    return os.environ.get("GALAXY_TRANSLATION_MODEL") or os.environ.get("OPENAI_MODEL") or DEFAULT_TRANSLATION_MODEL


def default_translation_base_url() -> str:
    return os.environ.get("GALAXY_TRANSLATION_BASE_URL") or os.environ.get("OPENAI_BASE_URL") or DEFAULT_TRANSLATION_BASE_URL


def default_translation_api_key() -> str:
    return os.environ.get("GALAXY_TRANSLATION_API_KEY") or os.environ.get("AI_TRANSLATION_API_KEY") or os.environ.get(
        "OPENAI_API_KEY", ""
    )


def validate_translation_options(options: AITranslationOptions) -> None:
    if not options.target_language or options.target_language == "none":
        return
    if _requires_api_key(options.base_url) and not options.api_key:
        raise RuntimeError(
            "AI translation needs an API key. Set OPENAI_API_KEY/GALAXY_TRANSLATION_API_KEY or enter it in the UI."
        )


def translate_cues(
    cues: list[SubtitleCue],
    options: AITranslationOptions,
    client: ChatClient | None = None,
) -> list[SubtitleCue]:
    if not cues:
        return []
    if options.target_language == "none":
        return cues

    validate_translation_options(options)
    chat_client = client or _chat_completion
    translated_texts = translate_texts([cue.text for cue in cues], options, client=chat_client)

    return [
        SubtitleCue(index=cue.index, start_ms=cue.start_ms, end_ms=cue.end_ms, text=translated_text)
        for cue, translated_text in zip(cues, translated_texts)
    ]


def translate_texts(
    texts: list[str],
    options: AITranslationOptions,
    client: ChatClient,
) -> list[str]:
    batch_size = max(1, min(50, int(options.batch_size)))
    translated: list[str] = []

    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        translated.extend(_translate_batch(batch, options, client))

    if len(translated) != len(texts):
        raise RuntimeError("AI translation returned a different number of subtitle lines.")

    return translated


def _translate_batch(texts: list[str], options: AITranslationOptions, client: ChatClient) -> list[str]:
    source = label_from_code(options.source_language, default=options.source_language or "Auto detect")
    target = label_from_code(options.target_language, default=options.target_language)
    payload = [{"index": index, "text": text} for index, text in enumerate(texts, start=1)]
    user_prompt = (
        f"Source language: {source}\n"
        f"Target language: {target}\n"
        "Translate these subtitle cues naturally for video viewers. Keep names, numbers, meaning, tone, and line order. "
        "Keep each translation concise enough for subtitles.\n\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )
    messages = [
        {
            "role": "system",
            "content": (
                "You are a professional subtitle translator. Return only valid JSON with this exact shape: "
                "{\"translations\":[\"...\"]}. The translations array must have exactly the same length and order "
                "as the input subtitle cues."
            ),
        },
        {"role": "user", "content": user_prompt},
    ]
    raw = client(messages, options)
    translations = _extract_translations(raw)
    if len(translations) != len(texts):
        raise RuntimeError(
            f"AI translation returned {len(translations)} lines for a batch that expected {len(texts)} lines."
        )
    return translations


def _extract_translations(raw: str) -> list[str]:
    cleaned = raw.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()

    data = json.loads(cleaned)
    if isinstance(data, dict):
        data = data.get("translations")
    if not isinstance(data, list):
        raise RuntimeError("AI translation response did not contain a translations array.")
    return [str(item).strip() for item in data]


def _chat_completion(messages: list[dict[str, str]], options: AITranslationOptions) -> str:
    url = options.base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": options.model,
        "messages": messages,
        "temperature": 0.2,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            **({"Authorization": f"Bearer {options.api_key}"} if options.api_key else {}),
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=120) as response:
            response_body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        details = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"AI translation API failed: {error.code} {details}") from error
    except urllib.error.URLError as error:
        raise RuntimeError(f"AI translation API failed: {error.reason}") from error

    data = json.loads(response_body)
    try:
        return str(data["choices"][0]["message"]["content"])
    except (KeyError, IndexError, TypeError) as error:
        raise RuntimeError("AI translation API returned an unexpected response.") from error


def _requires_api_key(base_url: str) -> bool:
    lowered = base_url.lower()
    return not any(host in lowered for host in ["localhost", "127.0.0.1", "0.0.0.0"])

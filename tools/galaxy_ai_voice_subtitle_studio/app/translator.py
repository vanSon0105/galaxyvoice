from __future__ import annotations

import json
import re
import unicodedata
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Callable

from .env_config import first_env
from .languages import label_from_code
from .srt import SubtitleCue

OPENAI_TRANSLATION_PROVIDER = "openai"
DEEPSEEK_TRANSLATION_PROVIDER = "deepseek"
DEFAULT_TRANSLATION_PROVIDER = OPENAI_TRANSLATION_PROVIDER
DEFAULT_TRANSLATION_BASE_URL = "https://api.openai.com/v1"
DEFAULT_TRANSLATION_MODEL = "gpt-4o-mini"
DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com"
DEFAULT_DEEPSEEK_MODEL = "deepseek-v4-flash"


@dataclass(frozen=True)
class TranslationProvider:
    code: str
    label: str
    default_model: str
    default_base_url: str
    api_key_env_names: tuple[str, ...]
    model_env_names: tuple[str, ...]
    base_url_env_names: tuple[str, ...]


TRANSLATION_PROVIDERS: dict[str, TranslationProvider] = {
    OPENAI_TRANSLATION_PROVIDER: TranslationProvider(
        code=OPENAI_TRANSLATION_PROVIDER,
        label="ChatGPT / OpenAI",
        default_model=DEFAULT_TRANSLATION_MODEL,
        default_base_url=DEFAULT_TRANSLATION_BASE_URL,
        api_key_env_names=(
            "GALAXY_OPENAI_API_KEY",
            "GALAXY_TRANSLATION_API_KEY",
            "AI_TRANSLATION_API_KEY",
            "OPENAI_API_KEY",
        ),
        model_env_names=("GALAXY_OPENAI_MODEL", "GALAXY_TRANSLATION_MODEL", "OPENAI_MODEL"),
        base_url_env_names=("GALAXY_OPENAI_BASE_URL", "GALAXY_TRANSLATION_BASE_URL", "OPENAI_BASE_URL"),
    ),
    DEEPSEEK_TRANSLATION_PROVIDER: TranslationProvider(
        code=DEEPSEEK_TRANSLATION_PROVIDER,
        label="DeepSeek",
        default_model=DEFAULT_DEEPSEEK_MODEL,
        default_base_url=DEFAULT_DEEPSEEK_BASE_URL,
        api_key_env_names=("GALAXY_DEEPSEEK_API_KEY", "DEEPSEEK_API_KEY"),
        model_env_names=("GALAXY_DEEPSEEK_MODEL", "DEEPSEEK_MODEL"),
        base_url_env_names=("GALAXY_DEEPSEEK_BASE_URL", "DEEPSEEK_BASE_URL"),
    ),
}


@dataclass(frozen=True)
class AITranslationOptions:
    source_language: str
    target_language: str
    provider: str = DEFAULT_TRANSLATION_PROVIDER
    api_key: str = ""
    model: str = ""
    base_url: str = ""
    batch_size: int = 20


ChatClient = Callable[[list[dict[str, str]], AITranslationOptions], str]

_TRANSLATION_ATTEMPTS = 2
_ENGLISH_WORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "but",
        "by",
        "can",
        "do",
        "for",
        "from",
        "have",
        "i",
        "in",
        "is",
        "it",
        "my",
        "not",
        "of",
        "on",
        "only",
        "or",
        "that",
        "the",
        "this",
        "to",
        "was",
        "we",
        "with",
        "you",
    }
)
_VIETNAMESE_COMBINING_MARKS = frozenset("\u0300\u0301\u0303\u0309\u0323\u0306\u031b")


def translation_provider_codes() -> list[str]:
    return list(TRANSLATION_PROVIDERS)


def translation_provider_labels() -> list[str]:
    return [provider.label for provider in TRANSLATION_PROVIDERS.values()]


def translation_provider_label(provider: str) -> str:
    return _provider_defaults(provider).label


def translation_provider_code(label_or_code: str) -> str:
    return normalize_translation_provider(label_or_code)


def normalize_translation_provider(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if not normalized:
        return DEFAULT_TRANSLATION_PROVIDER

    for code, provider in TRANSLATION_PROVIDERS.items():
        if normalized in {code, provider.label.lower()}:
            return code

    if "deepseek" in normalized:
        return DEEPSEEK_TRANSLATION_PROVIDER
    if "openai" in normalized or "chatgpt" in normalized or normalized == "chat":
        return OPENAI_TRANSLATION_PROVIDER

    return DEFAULT_TRANSLATION_PROVIDER


def default_translation_provider() -> str:
    return normalize_translation_provider(
        first_env("GALAXY_TRANSLATION_PROVIDER", "AI_TRANSLATION_PROVIDER", default=DEFAULT_TRANSLATION_PROVIDER)
    )


def default_translation_model(provider: str | None = None) -> str:
    defaults = _provider_defaults(provider or default_translation_provider())
    return first_env(*defaults.model_env_names, default=defaults.default_model)


def default_translation_base_url(provider: str | None = None) -> str:
    defaults = _provider_defaults(provider or default_translation_provider())
    return first_env(*defaults.base_url_env_names, default=defaults.default_base_url)


def default_translation_api_key(provider: str | None = None) -> str:
    defaults = _provider_defaults(provider or default_translation_provider())
    return first_env(*defaults.api_key_env_names)


def validate_translation_options(options: AITranslationOptions) -> None:
    options = resolve_translation_options(options)
    if not options.target_language or options.target_language == "none":
        return
    if _requires_api_key(options.base_url) and not options.api_key:
        provider = _provider_defaults(options.provider)
        env_hint = "/".join(provider.api_key_env_names)
        raise RuntimeError(
            f"{provider.label} translation needs an API key. Set {env_hint} or enter it in the UI."
        )


def translate_cues(
    cues: list[SubtitleCue],
    options: AITranslationOptions,
    client: ChatClient | None = None,
) -> list[SubtitleCue]:
    if not cues:
        return []
    options = resolve_translation_options(options)
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
    options = resolve_translation_options(options)
    batch_size = max(1, min(50, int(options.batch_size)))
    translated: list[str] = []

    for start in range(0, len(texts), batch_size):
        batch = texts[start : start + batch_size]
        translated.extend(_translate_batch(batch, options, client))

    if len(translated) != len(texts):
        raise RuntimeError("AI translation returned a different number of subtitle lines.")

    return translated


def translate_script_text(
    text: str,
    options: AITranslationOptions,
    client: ChatClient | None = None,
) -> str:
    options = resolve_translation_options(options)
    if options.target_language == "none" or _same_language(options.source_language, options.target_language):
        return text

    validate_translation_options(options)
    lines = text.splitlines()
    translatable = [line.strip() for line in lines if line.strip()]
    if not translatable:
        return text

    translated = translate_texts(translatable, options, client=client or _chat_completion)
    translated_iter = iter(translated)
    output_lines = [next(translated_iter) if line.strip() else line for line in lines]
    return "\n".join(output_lines).strip()


def _translate_batch(texts: list[str], options: AITranslationOptions, client: ChatClient) -> list[str]:
    source = label_from_code(options.source_language, default=options.source_language or "Auto detect")
    target = label_from_code(options.target_language, default=options.target_language)
    payload = [{"index": index, "text": text} for index, text in enumerate(texts, start=1)]
    wrong_language = ""
    for attempt in range(_TRANSLATION_ATTEMPTS):
        retry_instruction = (
            f"The previous response was written in {wrong_language}, not {target}. "
            f"Translate it into {target} now.\n"
            if attempt
            else ""
        )
        user_prompt = (
            f"Source language: {source}\n"
            f"Target language: {target} ({options.target_language})\n"
            f"{retry_instruction}"
            f"Translate every cue directly into {target}. Do not use English unless the target language is English. "
            "Keep names, numbers, meaning, tone, and line order. Keep each translation concise enough for subtitles.\n\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )
        messages = [
            {
                "role": "system",
                "content": (
                    f"You are a professional subtitle translator. Every translated sentence must be written in "
                    f"{target}. Never substitute another language. Return only valid JSON with this exact shape: "
                    "{\"translations\":[\"...\"]}. The translations array must have exactly the same length and "
                    "order as the input subtitle cues."
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
        detected_language = _wrong_output_language(translations, options.target_language)
        if detected_language is None:
            return translations
        wrong_language = detected_language

    raise RuntimeError(
        f"AI translation returned {wrong_language or 'another language'} instead of Vietnamese after retrying. "
        "No mixed-language subtitle file was created."
    )


def _wrong_output_language(translations: list[str], target_language: str) -> str | None:
    if target_language.strip().lower() != "vi":
        return None

    combined = " ".join(translations)
    han_characters = sum(_is_han(character) for character in combined)
    alphabetic_characters = sum(character.isalpha() for character in combined)
    if han_characters >= 4 and han_characters * 2 >= alphabetic_characters:
        return "Chinese"

    words = re.findall(r"[a-z]+", combined.lower())
    if len(words) < 12:
        return None

    normalized = unicodedata.normalize("NFD", combined)
    vietnamese_marks = sum(
        character in _VIETNAMESE_COMBINING_MARKS or character in {"đ", "Đ"}
        for character in normalized
    )
    english_words = sum(word in _ENGLISH_WORDS for word in words)
    if vietnamese_marks < 2 and english_words >= max(4, len(words) // 8):
        return "English"
    return None


def _is_han(character: str) -> bool:
    codepoint = ord(character)
    return (
        0x3400 <= codepoint <= 0x4DBF
        or 0x4E00 <= codepoint <= 0x9FFF
        or 0xF900 <= codepoint <= 0xFAFF
    )


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
    options = resolve_translation_options(options)
    url = options.base_url.rstrip("/") + "/chat/completions"
    body = {
        "model": options.model,
        "messages": messages,
        "temperature": 0.2,
    }
    if normalize_translation_provider(options.provider) == DEEPSEEK_TRANSLATION_PROVIDER:
        body["thinking"] = {"type": "disabled"}

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


def _same_language(source_language: str, target_language: str) -> bool:
    source = source_language.strip().lower()
    target = target_language.strip().lower()
    return bool(source and target and source != "auto" and source == target)


def resolve_translation_options(options: AITranslationOptions) -> AITranslationOptions:
    provider = normalize_translation_provider(options.provider)
    return AITranslationOptions(
        source_language=options.source_language,
        target_language=options.target_language,
        provider=provider,
        api_key=options.api_key or default_translation_api_key(provider),
        model=options.model or default_translation_model(provider),
        base_url=options.base_url or default_translation_base_url(provider),
        batch_size=options.batch_size,
    )


def _provider_defaults(provider: str | None) -> TranslationProvider:
    return TRANSLATION_PROVIDERS[normalize_translation_provider(provider)]

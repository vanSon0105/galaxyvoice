from __future__ import annotations

import json
import re
import unicodedata
import urllib.error
import urllib.request
from concurrent.futures import CancelledError, FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .cache import read_json, stable_digest, write_json_atomic
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
    max_workers: int = 1


ChatClient = Callable[[list[dict[str, str]], AITranslationOptions], str]
TranslationProgressCallback = Callable[[int, int], None]
TranslationWarningCallback = Callable[[str], None]

_TRANSLATION_ATTEMPTS = 2
_TRANSLATION_CHECKPOINT_VERSION = 1
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
        "done",
        "explosion",
        "finish",
        "finished",
        "for",
        "from",
        "have",
        "hello",
        "help",
        "i",
        "in",
        "is",
        "it",
        "my",
        "not",
        "please",
        "ready",
        "run",
        "of",
        "on",
        "only",
        "or",
        "second",
        "sorry",
        "start",
        "stop",
        "that",
        "the",
        "this",
        "to",
        "was",
        "wait",
        "we",
        "welcome",
        "with",
        "you",
    }
)
_VIETNAMESE_UNMARKED_WORDS = frozenset(
    {
        "ai",
        "anh",
        "ba",
        "cho",
        "con",
        "em",
        "gai",
        "gan",
        "hay",
        "khi",
        "kho",
        "la",
        "lo",
        "mai",
        "nam",
        "ngang",
        "nhanh",
        "nay",
        "nghe",
        "nghi",
        "nha",
        "nho",
        "phim",
        "qua",
        "quen",
        "ra",
        "sao",
        "ta",
        "tai",
        "thi",
        "thu",
        "trai",
        "tre",
        "trong",
        "vui",
        "xin",
    }
)
_VIETNAMESE_COMBINING_MARKS = frozenset("\u0300\u0301\u0302\u0303\u0309\u0323\u0306\u031b")


class _PartialTranslationError(Exception):
    def __init__(self, translations: dict[int, str], original: Exception) -> None:
        super().__init__(str(original))
        self.translations = translations
        self.original = original


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
    progress: TranslationProgressCallback | None = None,
    checkpoint_path: Path | None = None,
    warning: TranslationWarningCallback | None = None,
) -> list[SubtitleCue]:
    if not cues:
        return []
    options = resolve_translation_options(options)
    if options.target_language == "none":
        return cues

    validate_translation_options(options)
    chat_client = client or _chat_completion
    translated_texts = translate_texts(
        [cue.text for cue in cues],
        options,
        client=chat_client,
        progress=progress,
        checkpoint_path=checkpoint_path,
        warning=warning,
    )

    return [
        SubtitleCue(index=cue.index, start_ms=cue.start_ms, end_ms=cue.end_ms, text=translated_text)
        for cue, translated_text in zip(cues, translated_texts)
    ]


def translate_texts(
    texts: list[str],
    options: AITranslationOptions,
    client: ChatClient,
    progress: TranslationProgressCallback | None = None,
    checkpoint_path: Path | None = None,
    warning: TranslationWarningCallback | None = None,
) -> list[str]:
    options = resolve_translation_options(options)
    batch_size = max(1, min(50, int(options.batch_size)))
    max_workers = max(1, min(6, int(options.max_workers)))
    checkpoint_id = _translation_checkpoint_id(texts, options)
    completed = _load_translation_checkpoint(checkpoint_path, checkpoint_id, texts, options)
    translated: list[str | None] = [completed.get(index) for index in range(len(texts))]
    if progress is not None:
        progress(len(completed), len(texts))

    pending = [(index, text) for index, text in enumerate(texts) if translated[index] is None]
    batches = [pending[start : start + batch_size] for start in range(0, len(pending), batch_size)]
    checkpoint_writable = checkpoint_path is not None

    def store_entries(entries: list[tuple[int, str]]) -> None:
        nonlocal checkpoint_writable
        if not entries:
            return
        for index, translated_text in entries:
            translated[index] = translated_text
            completed[index] = translated_text
        if checkpoint_writable:
            save_error = _save_translation_checkpoint(checkpoint_path, checkpoint_id, completed)
            if save_error is not None:
                checkpoint_writable = False
                if warning is not None:
                    warning(f"Could not save translation checkpoint: {save_error}")
        if progress is not None:
            progress(len(completed), len(texts))

    def store_batch(batch: list[tuple[int, str]], batch_translations: list[str]) -> None:
        if len(batch_translations) != len(batch):
            raise RuntimeError("AI translation returned a different number of subtitle lines.")
        store_entries(
            [(index, translated_text) for (index, _text), translated_text in zip(batch, batch_translations)]
        )

    def store_partial(batch: list[tuple[int, str]], error: _PartialTranslationError) -> None:
        store_entries(
            [
                (batch[local_index][0], translated_text)
                for local_index, translated_text in sorted(error.translations.items())
                if 0 <= local_index < len(batch)
            ]
        )

    if max_workers == 1 or len(batches) <= 1:
        for batch in batches:
            try:
                batch_translations = _translate_batch([text for _index, text in batch], options, client)
            except _PartialTranslationError as error:
                store_partial(batch, error)
                raise error.original
            store_batch(batch, batch_translations)
    else:
        worker_count = min(max_workers, len(batches))
        executor = ThreadPoolExecutor(max_workers=worker_count)
        batch_iterator = iter(batches)
        futures: dict[Future[list[str]], list[tuple[int, str]]] = {}

        def submit_next_batch() -> bool:
            try:
                batch = next(batch_iterator)
            except StopIteration:
                return False
            future = executor.submit(_translate_batch, [text for _index, text in batch], options, client)
            futures[future] = batch
            return True

        for _ in range(worker_count):
            submit_next_batch()

        first_error: Exception | None = None
        try:
            while futures:
                done, _not_done = wait(tuple(futures), return_when=FIRST_COMPLETED)
                for future in done:
                    batch = futures.pop(future)
                    try:
                        batch_translations = future.result()
                    except CancelledError:
                        continue
                    except _PartialTranslationError as error:
                        store_partial(batch, error)
                        if first_error is None:
                            first_error = error.original
                    except Exception as error:
                        if first_error is None:
                            first_error = error
                    else:
                        store_batch(batch, batch_translations)

                if first_error is None:
                    while len(futures) < worker_count and submit_next_batch():
                        pass
                else:
                    for future in futures:
                        future.cancel()
        finally:
            executor.shutdown(wait=True, cancel_futures=True)
        if first_error is not None:
            raise first_error

    if any(text is None for text in translated):
        raise RuntimeError("AI translation returned a different number of subtitle lines.")
    return [str(text) for text in translated]


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


def _translation_checkpoint_id(texts: list[str], options: AITranslationOptions) -> str:
    return stable_digest(
        {
            "version": _TRANSLATION_CHECKPOINT_VERSION,
            **_translation_identity(options),
            "texts": texts,
        }
    )


def _translation_identity(options: AITranslationOptions) -> dict[str, str]:
    return {
        "source_language": options.source_language,
        "target_language": options.target_language,
        "provider": options.provider,
        "model": options.model,
        "base_url": options.base_url,
    }


def translation_checkpoint_path(
    cache_dir: Path,
    cues: list[SubtitleCue],
    options: AITranslationOptions,
) -> Path:
    resolved_options = resolve_translation_options(options)
    path_id = stable_digest(
        {
            **_translation_identity(resolved_options),
            "cues": [
                [cue.index, cue.start_ms, cue.end_ms, cue.text]
                for cue in cues
            ],
        }
    )
    return cache_dir / "translations" / f"{path_id}.json"


def _load_translation_checkpoint(
    path: Path | None,
    checkpoint_id: str,
    texts: list[str],
    options: AITranslationOptions,
) -> dict[int, str]:
    if path is None:
        return {}
    payload = read_json(path)
    if not isinstance(payload, dict) or payload.get("checkpoint_id") != checkpoint_id:
        return {}
    raw_translations = payload.get("translations")
    if not isinstance(raw_translations, dict):
        return {}

    translations: dict[int, str] = {}
    for raw_index, raw_text in raw_translations.items():
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        translated_text = raw_text.strip() if isinstance(raw_text, str) else ""
        if not 0 <= index < len(texts) or not translated_text:
            continue
        if _wrong_output_language(
            [translated_text],
            options.target_language,
            source_texts=[texts[index]],
        ) is not None:
            continue
        translations[index] = translated_text
    return translations


def _save_translation_checkpoint(
    path: Path | None,
    checkpoint_id: str,
    translations: dict[int, str],
) -> OSError | None:
    if path is None:
        return None
    try:
        write_json_atomic(
            path,
            {
                "version": _TRANSLATION_CHECKPOINT_VERSION,
                "checkpoint_id": checkpoint_id,
                "translations": {str(index): text for index, text in sorted(translations.items())},
            },
        )
    except OSError as error:
        return error
    return None


def _translate_batch(texts: list[str], options: AITranslationOptions, client: ChatClient) -> list[str]:
    source = label_from_code(options.source_language, default=options.source_language or "Auto detect")
    target = label_from_code(options.target_language, default=options.target_language)
    payload = [{"index": index, "text": text} for index, text in enumerate(texts, start=1)]
    wrong_language = ""
    for attempt in range(_TRANSLATION_ATTEMPTS):
        messages = _translation_messages(
            source=source,
            target=target,
            target_language=options.target_language,
            payload=payload,
            wrong_language=wrong_language if attempt else "",
        )
        raw = client(messages, options)
        translations = _extract_translations(raw)
        if len(translations) != len(texts):
            raise RuntimeError(
                f"AI translation returned {len(translations)} lines for a batch that expected {len(texts)} lines."
            )
        detected_languages = [
            _wrong_output_language(
                [translation],
                options.target_language,
                source_texts=[texts[index]],
            )
            for index, translation in enumerate(translations)
        ]
        wrong_indexes = [
            index for index, detected_language in enumerate(detected_languages) if detected_language is not None
        ]
        if not wrong_indexes:
            return translations
        if len(wrong_indexes) < len(texts):
            partial_translations = {
                index: translation
                for index, translation in enumerate(translations)
                if index not in wrong_indexes
            }
            try:
                corrected = _translate_batch([texts[index] for index in wrong_indexes], options, client)
            except _PartialTranslationError as error:
                for nested_index, translated_text in error.translations.items():
                    if 0 <= nested_index < len(wrong_indexes):
                        partial_translations[wrong_indexes[nested_index]] = translated_text
                raise _PartialTranslationError(partial_translations, error.original) from error
            except Exception as error:
                raise _PartialTranslationError(partial_translations, error) from error
            for index, corrected_text in zip(wrong_indexes, corrected):
                translations[index] = corrected_text
            return translations

        detected_language = detected_languages[0]
        if detected_language == "Chinese" and len(texts) > 1:
            midpoint = len(texts) // 2
            return _translate_split_batch(texts, midpoint, options, client)
        wrong_language = detected_language

    if len(texts) == 1 and wrong_language == "Chinese" and options.target_language.strip().lower() == "vi":
        direct_translation = _translate_chinese_cue_directly(texts[0], options, client)
        if _wrong_output_language(
            [direct_translation],
            options.target_language,
            source_texts=texts,
        ) is None:
            return [direct_translation]

    raise RuntimeError(
        f"AI translation returned {wrong_language or 'another language'} instead of Vietnamese after retrying. "
        "No mixed-language subtitle file was created."
    )


def _translate_split_batch(
    texts: list[str],
    midpoint: int,
    options: AITranslationOptions,
    client: ChatClient,
) -> list[str]:
    translated: dict[int, str] = {}
    first_error: Exception | None = None
    for offset, subset in ((0, texts[:midpoint]), (midpoint, texts[midpoint:])):
        try:
            subset_translations = _translate_batch(subset, options, client)
        except _PartialTranslationError as error:
            for local_index, translated_text in error.translations.items():
                translated[offset + local_index] = translated_text
            if first_error is None:
                first_error = error.original
        except Exception as error:
            if first_error is None:
                first_error = error
        else:
            for local_index, translated_text in enumerate(subset_translations):
                translated[offset + local_index] = translated_text

    if first_error is not None:
        raise _PartialTranslationError(translated, first_error) from first_error
    return [translated[index] for index in range(len(texts))]


def _translation_messages(
    source: str,
    target: str,
    target_language: str,
    payload: list[dict[str, object]],
    wrong_language: str,
) -> list[dict[str, str]]:
    if target_language.strip().lower() == "vi":
        source_description = (
            "t\u1ef1 nh\u1eadn di\u1ec7n" if source.lower() == "auto detect" else source
        )
        retry_instruction = (
            f"Ph\u1ea3n h\u1ed3i tr\u01b0\u1edbc v\u1eabn \u0111\u01b0\u1ee3c vi\u1ebft b\u1eb1ng {wrong_language}, kh\u00f4ng ph\u1ea3i ti\u1ebfng Vi\u1ec7t. "
            "H\u00e3y d\u1ecbch l\u1ea1i ho\u00e0n to\u00e0n.\n"
            if wrong_language
            else ""
        )
        return [
            {
                "role": "system",
                "content": (
                    "B\u1ea1n l\u00e0 bi\u00ean d\u1ecbch ph\u1ee5 \u0111\u1ec1 chuy\u00ean nghi\u1ec7p. Nhi\u1ec7m v\u1ee5 duy nh\u1ea5t l\u00e0 d\u1ecbch "
                    "t\u1eebng c\u00e2u sang ti\u1ebfng Vi\u1ec7t t\u1ef1 nhi\u00ean. M\u1ecdi ph\u1ea7n t\u1eed trong translations ph\u1ea3i b\u1eb1ng "
                    "ti\u1ebfng Vi\u1ec7t; kh\u00f4ng \u0111\u01b0\u1ee3c tr\u1ea3 nguy\u00ean c\u00e2u b\u1eb1ng ti\u1ebfng Trung ho\u1eb7c ti\u1ebfng Anh. "
                    "Gi\u1eef t\u00ean ri\u00eang, s\u1ed1, \u00fd ngh\u0129a, gi\u1ecdng \u0111i\u1ec7u v\u00e0 th\u1ee9 t\u1ef1. N\u1ebfu b\u1ea3n d\u1ecbch ch\u1ec9 c\u00f3 "
                    "t\u00ean ri\u00eang Latin kh\u00f4ng d\u1ea5u, h\u00e3y th\u00eam ng\u1eef c\u1ea3nh ti\u1ebfng Vi\u1ec7t ng\u1eafn g\u1ecdn. N\u1ebfu c\u00e2u ngu\u1ed3n nh\u1eadn d\u1ea1ng "
                    "ch\u01b0a chu\u1ea9n, h\u00e3y d\u1ecbch theo ngh\u0129a h\u1ee3p l\u00fd nh\u1ea5t. Ch\u1ec9 tr\u1ea3 v\u1ec1 JSON h\u1ee3p l\u1ec7 d\u1ea1ng "
                    "{\"translations\":[\"...\"]}, \u0111\u00fang s\u1ed1 l\u01b0\u1ee3ng v\u00e0 th\u1ee9 t\u1ef1 c\u00e2u."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Source language: {source_description}\n"
                    "Target language: Vietnamese (vi)\n"
                    f"{retry_instruction}"
                    "V\u00ed d\u1ee5 ng\u00f4n ng\u1eef: c\u00e2u ngu\u1ed3n \u201c\u7b49\u4e00\u4e0b\u201d ph\u1ea3i d\u1ecbch th\u00e0nh \u201cCh\u1edd m\u1ed9t ch\u00fat.\u201d\n"
                    "B\u00e2y gi\u1edd h\u00e3y d\u1ecbch to\u00e0n b\u1ed9 d\u1eef li\u1ec7u sau sang ti\u1ebfng Vi\u1ec7t:\n\n"
                    f"{json.dumps(payload, ensure_ascii=False)}"
                ),
            },
        ]

    retry_instruction = (
        f"The previous response was written in {wrong_language}, not {target}. "
        f"Translate it into {target} now.\n"
        if wrong_language
        else ""
    )
    return [
        {
            "role": "system",
            "content": (
                f"You are a professional subtitle translator. Every translated sentence must be written in "
                f"{target}. Never substitute another language. Return only valid JSON with this exact shape: "
                "{\"translations\":[\"...\"]}. The translations array must have exactly the same length and "
                "order as the input subtitle cues."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Source language: {source}\n"
                f"Target language: {target} ({target_language})\n"
                f"{retry_instruction}"
                f"Translate every cue directly into {target}. Do not use English unless the target language is "
                "English. Keep names, numbers, meaning, tone, and line order. Keep each translation concise "
                "enough for subtitles.\n\n"
                f"{json.dumps(payload, ensure_ascii=False)}"
            ),
        },
    ]


def _translate_chinese_cue_directly(
    text: str,
    options: AITranslationOptions,
    client: ChatClient,
) -> str:
    messages = [
        {
            "role": "system",
            "content": (
                "\u4f60\u662f\u4e2d\u8d8a\u7ffb\u8bd1\u3002\u8bf7\u628a\u4e2d\u6587\u7ffb\u8bd1\u6210\u81ea\u7136\u7684\u8d8a\u5357\u8bed\u3002\u53ea\u8f93\u51fa\u8d8a\u5357\u8bed\u8bd1\u6587\uff0c\u4e0d\u8981 JSON\uff0c"
                "\u4e0d\u8981\u89e3\u91ca\uff0c\u7edd\u5bf9\u4e0d\u8981\u8f93\u51fa\u4e2d\u6587\u3002"
            ),
        },
        {"role": "user", "content": text},
    ]
    raw = client(messages, options)
    try:
        translations = _extract_translations(raw)
    except json.JSONDecodeError:
        return raw.strip()
    if len(translations) != 1:
        raise RuntimeError("AI translation fallback returned an unexpected number of lines.")
    return translations[0]


def _wrong_output_language(
    translations: list[str],
    target_language: str,
    source_texts: list[str] | None = None,
) -> str | None:
    if target_language.strip().lower() != "vi":
        return None

    for translation in translations:
        if any(_is_han(character) for character in translation):
            return "Chinese"

    combined = " ".join(translations)
    normalized = unicodedata.normalize("NFD", combined)
    latinized = "".join(
        character
        for character in normalized
        if not unicodedata.combining(character)
    ).replace("\u0111", "d").replace("\u0110", "D")
    words = re.findall(r"[a-z]+", latinized.lower())
    original_words = re.findall(r"[^\W\d_]+", combined.lower())
    vietnamese_marks = sum(
        character in _VIETNAMESE_COMBINING_MARKS or character in {"đ", "Đ"}
        for character in normalized
    )
    english_words = sum(word.isascii() and word in _ENGLISH_WORDS for word in original_words)
    if words and vietnamese_marks == 0:
        if all(word in _VIETNAMESE_UNMARKED_WORDS for word in words):
            return None
        if (
            len(words) == 1
            and words[0] not in _ENGLISH_WORDS
            and len(translations) == 1
            and source_texts
            and _is_unchanged_single_name(translations[0], source_texts[0])
        ):
            return None
        return "English"
    if vietnamese_marks and english_words >= 2:
        return "English"
    if len(words) < 12:
        return None
    if vietnamese_marks < 2 and english_words >= max(4, len(words) // 8):
        return "English"
    return None


def _is_unchanged_single_name(translation: str, source_text: str) -> bool:
    normalized_translation = " ".join(translation.split())
    if normalized_translation.casefold() != " ".join(source_text.split()).casefold():
        return False
    if any(_is_han(character) for character in source_text):
        return False
    tokens = re.findall(r"[A-Za-z][A-Za-z0-9'-]*", normalized_translation)
    return len(tokens) == 1 and (
        tokens[0].isupper()
        or tokens[0][0].isupper()
        or any(character.isdigit() for character in tokens[0])
    )


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
        max_workers=options.max_workers,
    )


def _provider_defaults(provider: str | None) -> TranslationProvider:
    return TRANSLATION_PROVIDERS[normalize_translation_provider(provider)]

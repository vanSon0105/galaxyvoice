from __future__ import annotations

LANGUAGE_CHOICES: list[tuple[str, str]] = [
    ("auto", "Auto detect"),
    ("en", "English"),
    ("vi", "Vietnamese"),
    ("ja", "Japanese"),
    ("ko", "Korean"),
    ("zh", "Chinese"),
    ("th", "Thai"),
    ("id", "Indonesian"),
    ("fr", "French"),
    ("de", "German"),
    ("es", "Spanish"),
    ("ru", "Russian"),
]

TARGET_LANGUAGE_CHOICES: list[tuple[str, str]] = [
    ("none", "No translation"),
    *[(code, label) for code, label in LANGUAGE_CHOICES if code != "auto"],
]


def language_labels(include_auto: bool = True, include_none: bool = False) -> list[str]:
    choices = TARGET_LANGUAGE_CHOICES if include_none else LANGUAGE_CHOICES
    if not include_auto:
        choices = [(code, label) for code, label in choices if code != "auto"]
    return [label for _code, label in choices]


def code_from_label(label: str, default: str = "auto") -> str:
    normalized = label.strip().lower()
    for code, language_label in [*LANGUAGE_CHOICES, *TARGET_LANGUAGE_CHOICES]:
        if normalized in {code.lower(), language_label.lower()}:
            return code
    return default


def label_from_code(code: str, default: str = "Auto detect") -> str:
    normalized = code.strip().lower()
    for language_code, label in [*LANGUAGE_CHOICES, *TARGET_LANGUAGE_CHOICES]:
        if normalized == language_code.lower():
            return label
    return default

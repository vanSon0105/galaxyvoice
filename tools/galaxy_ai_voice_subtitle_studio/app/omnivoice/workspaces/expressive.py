from __future__ import annotations

import re
import shlex
from dataclasses import asdict, dataclass
from typing import Iterable
from uuid import uuid4


SPEECH_DIRECTIVE = "speech"
PAUSE_DIRECTIVE = "pause"
_TAG_RE = re.compile(r"\[(/?)([a-z][a-z-]*)(?:\s+([^\]]*?))?\]", re.IGNORECASE)
_PAIRED_TAGS = frozenset({"rate", "slow", "fast", "emphasis", "spell", "emotion", "pronounce", "phoneme"})
_EVENT_TAGS = frozenset({
    "laughter",
    "sigh",
    "confirmation-en",
    "question-en",
    "question-ah",
    "question-oh",
    "surprise-ah",
    "surprise-oh",
    "surprise-wa",
    "dissatisfaction-hnn",
})
_KNOWN_TAGS = _PAIRED_TAGS | _EVENT_TAGS | {"pause"}


@dataclass(frozen=True)
class PronunciationRule:
    rule_id: str
    source: str
    replacement: str
    language: str = ""
    case_sensitive: bool = False
    whole_word: bool = True

    @classmethod
    def create(
        cls,
        source: str,
        replacement: str,
        *,
        language: str = "",
        case_sensitive: bool = False,
        whole_word: bool = True,
    ) -> "PronunciationRule":
        return cls(
            rule_id=f"pron-{uuid4().hex[:12]}",
            source=source.strip(),
            replacement=replacement.strip(),
            language=language.strip().lower(),
            case_sensitive=case_sensitive,
            whole_word=whole_word,
        )

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class ExpressiveCapabilities:
    rate: bool = True
    emphasis_instruction: bool = True
    emotion_instruction: bool = True
    phoneme: bool = False


@dataclass(frozen=True)
class ExpressiveIssue:
    code: str
    message: str
    severity: str = "warning"
    offset: int = 0


@dataclass(frozen=True)
class ExpressiveDirective:
    kind: str
    spoken_text: str = ""
    display_text: str = ""
    pause_ms: int = 0
    rate: float = 1.0
    emphasis: bool = False
    spell: bool = False
    emotion: str = ""
    instruction: str = ""


@dataclass(frozen=True)
class ExpressiveCompileResult:
    directives: tuple[ExpressiveDirective, ...]
    issues: tuple[ExpressiveIssue, ...]


@dataclass(frozen=True)
class _State:
    rate: float = 1.0
    emphasis: bool = False
    spell: bool = False
    emotion: str = ""


def compile_expressive_text(
    source: str,
    *,
    language: str = "auto",
    pronunciation_rules: Iterable[PronunciationRule] = (),
    capabilities: ExpressiveCapabilities | None = None,
    base_rate: float = 1.0,
    base_spell: bool = False,
) -> ExpressiveCompileResult:
    """Compile Galaxy markup into engine-neutral speech and pause directives."""

    directives: list[ExpressiveDirective] = []
    issues: list[ExpressiveIssue] = []
    rules = tuple(rule for rule in pronunciation_rules if rule.source and rule.replacement)
    resolved_capabilities = capabilities or ExpressiveCapabilities()
    _compile_range(
        source,
        0,
        len(source),
        _State(rate=_clamp_rate(base_rate), spell=base_spell),
        language.strip().lower() or "auto",
        rules,
        resolved_capabilities,
        directives,
        issues,
    )
    return ExpressiveCompileResult(tuple(directives), tuple(issues))


def expression_instruction(*, emphasis: bool = False, emotion: str = "") -> str:
    parts: list[str] = []
    if emotion.strip():
        parts.append(f"Speak with a {emotion.strip()} emotion.")
    if emphasis:
        parts.append("Emphasize this phrase clearly.")
    return " ".join(parts)


def pronunciation_rules_from_payload(payload: object) -> tuple[PronunciationRule, ...]:
    if not isinstance(payload, list):
        return ()
    rules: list[PronunciationRule] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        source = str(item.get("source") or "").strip()
        replacement = str(item.get("replacement") or "").strip()
        if not source or not replacement:
            continue
        rules.append(
            PronunciationRule(
                rule_id=str(item.get("rule_id") or f"pron-{uuid4().hex[:12]}"),
                source=source,
                replacement=replacement,
                language=str(item.get("language") or "").strip().lower(),
                case_sensitive=bool(item.get("case_sensitive", False)),
                whole_word=bool(item.get("whole_word", True)),
            )
        )
    return tuple(rules)


def _compile_range(
    source: str,
    start: int,
    end: int,
    state: _State,
    language: str,
    rules: tuple[PronunciationRule, ...],
    capabilities: ExpressiveCapabilities,
    directives: list[ExpressiveDirective],
    issues: list[ExpressiveIssue],
) -> None:
    cursor = start
    while cursor < end:
        match = _TAG_RE.search(source, cursor, end)
        if match is None:
            _append_speech(source[cursor:end], state, language, rules, capabilities, directives, issues, cursor)
            return
        if match.start() > cursor:
            _append_speech(source[cursor:match.start()], state, language, rules, capabilities, directives, issues, cursor)
        closing, raw_name, raw_argument = match.groups()
        name = raw_name.casefold()
        if closing:
            issues.append(ExpressiveIssue("unexpected-close", f"Thẻ đóng [/{name}] không có thẻ mở.", "error", match.start()))
            _append_speech(match.group(0), state, language, rules, capabilities, directives, issues, match.start())
            cursor = match.end()
            continue
        if name not in _KNOWN_TAGS:
            issues.append(ExpressiveIssue("unknown-tag", f"Không hỗ trợ thẻ [{name}].", "warning", match.start()))
            _append_speech(match.group(0), state, language, rules, capabilities, directives, issues, match.start())
            cursor = match.end()
            continue
        if name == "pause":
            pause_ms = _parse_pause(raw_argument or "", match.start(), issues)
            if pause_ms is not None:
                directives.append(ExpressiveDirective(kind=PAUSE_DIRECTIVE, pause_ms=pause_ms))
            cursor = match.end()
            continue
        if name in _EVENT_TAGS:
            directives.append(
                ExpressiveDirective(
                    kind=SPEECH_DIRECTIVE,
                    spoken_text=match.group(0),
                    display_text=match.group(0),
                    rate=state.rate,
                    emphasis=state.emphasis,
                    spell=state.spell,
                    emotion=state.emotion,
                    instruction=expression_instruction(
                        emphasis=state.emphasis,
                        emotion=state.emotion,
                    ),
                )
            )
            cursor = match.end()
            continue

        close = _find_closing_tag(source, match.end(), end, name)
        if close is None:
            issues.append(ExpressiveIssue("unclosed-tag", f"Thẻ [{name}] chưa được đóng.", "error", match.start()))
            inner_end = end
            next_cursor = end
        else:
            inner_end, next_cursor = close
        argument = _parse_argument(raw_argument or "")
        inner_source = source[match.end():inner_end]
        if name in {"pronounce", "phoneme"}:
            _append_explicit_pronunciation(
                name,
                argument,
                inner_source,
                state,
                language,
                rules,
                capabilities,
                directives,
                issues,
                match.start(),
            )
        else:
            next_state = _state_for_tag(name, argument, state, capabilities, issues, match.start())
            _compile_range(
                source,
                match.end(),
                inner_end,
                next_state,
                language,
                rules,
                capabilities,
                directives,
                issues,
            )
        cursor = next_cursor


def _append_speech(
    text: str,
    state: _State,
    language: str,
    rules: tuple[PronunciationRule, ...],
    capabilities: ExpressiveCapabilities,
    directives: list[ExpressiveDirective],
    issues: list[ExpressiveIssue],
    offset: int,
) -> None:
    display = re.sub(r"\s+", " ", text).strip()
    if not display:
        return
    spoken = _apply_pronunciation_rules(display, language, rules)
    if state.spell:
        spoken = " ".join(character for character in spoken if not character.isspace())
    instruction = expression_instruction(
        emphasis=state.emphasis and capabilities.emphasis_instruction,
        emotion=state.emotion if capabilities.emotion_instruction else "",
    )
    if state.emphasis and not capabilities.emphasis_instruction:
        issues.append(ExpressiveIssue("emphasis-degraded", "Engine hiện tại không hỗ trợ nhấn mạnh; nội dung vẫn được đọc.", "warning", offset))
    if state.emotion and not capabilities.emotion_instruction:
        issues.append(ExpressiveIssue("emotion-degraded", f"Engine hiện tại không hỗ trợ cảm xúc '{state.emotion}'.", "warning", offset))
    directives.append(
        ExpressiveDirective(
            kind=SPEECH_DIRECTIVE,
            spoken_text=spoken,
            display_text=display,
            rate=state.rate if capabilities.rate else 1.0,
            emphasis=state.emphasis,
            spell=state.spell,
            emotion=state.emotion,
            instruction=instruction,
        )
    )


def _append_explicit_pronunciation(
    name: str,
    argument: str,
    inner_source: str,
    state: _State,
    language: str,
    rules: tuple[PronunciationRule, ...],
    capabilities: ExpressiveCapabilities,
    directives: list[ExpressiveDirective],
    issues: list[ExpressiveIssue],
    offset: int,
) -> None:
    display = re.sub(_TAG_RE, "", inner_source)
    display = re.sub(r"\s+", " ", display).strip()
    if not display:
        issues.append(ExpressiveIssue("empty-pronunciation", f"Thẻ [{name}] không có nội dung.", "error", offset))
        return
    if not argument:
        issues.append(ExpressiveIssue("missing-pronunciation", f"Thẻ [{name}] chưa có cách đọc.", "error", offset))
        spoken = _apply_pronunciation_rules(display, language, rules)
    elif name == "phoneme" and not capabilities.phoneme:
        spoken = _apply_pronunciation_rules(display, language, rules)
        issues.append(ExpressiveIssue("phoneme-degraded", "Engine không nhận phoneme; đã dùng quy tắc phát âm hoặc chữ gốc.", "warning", offset))
    else:
        spoken = argument if name == "pronounce" else display
    if state.spell:
        spoken = " ".join(character for character in spoken if not character.isspace())
    directives.append(
        ExpressiveDirective(
            kind=SPEECH_DIRECTIVE,
            spoken_text=spoken,
            display_text=display,
            rate=state.rate,
            emphasis=state.emphasis,
            spell=state.spell,
            emotion=state.emotion,
            instruction=expression_instruction(emphasis=state.emphasis, emotion=state.emotion),
        )
    )


def _find_closing_tag(source: str, start: int, end: int, name: str) -> tuple[int, int] | None:
    depth = 1
    for match in _TAG_RE.finditer(source, start, end):
        closing, raw_name, _argument = match.groups()
        if raw_name.casefold() != name:
            continue
        depth += -1 if closing else 1
        if depth == 0:
            return match.start(), match.end()
    return None


def _state_for_tag(
    name: str,
    argument: str,
    state: _State,
    capabilities: ExpressiveCapabilities,
    issues: list[ExpressiveIssue],
    offset: int,
) -> _State:
    if name == "slow":
        return _State(_clamp_rate(state.rate * 0.85), state.emphasis, state.spell, state.emotion)
    if name == "fast":
        return _State(_clamp_rate(state.rate * 1.15), state.emphasis, state.spell, state.emotion)
    if name == "rate":
        try:
            rate = float(argument)
            if not 0.5 <= rate <= 1.5:
                raise ValueError
        except (TypeError, ValueError):
            issues.append(ExpressiveIssue("invalid-rate", "[rate] cần một số từ 0.5 đến 1.5.", "error", offset))
            rate = state.rate
        if not capabilities.rate:
            issues.append(ExpressiveIssue("rate-degraded", "Engine hiện tại không hỗ trợ đổi tốc độ.", "warning", offset))
        return _State(rate, state.emphasis, state.spell, state.emotion)
    if name == "emphasis":
        return _State(state.rate, True, state.spell, state.emotion)
    if name == "spell":
        return _State(state.rate, state.emphasis, True, state.emotion)
    if name == "emotion":
        if not argument:
            issues.append(ExpressiveIssue("missing-emotion", "[emotion] cần tên cảm xúc.", "error", offset))
        return _State(state.rate, state.emphasis, state.spell, argument.strip().lower())
    return state


def _parse_pause(argument: str, offset: int, issues: list[ExpressiveIssue]) -> int | None:
    normalized = argument.strip().lower() or "500ms"
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(ms|s)?", normalized)
    if match is None:
        issues.append(ExpressiveIssue("invalid-pause", "[pause] cần thời lượng như 500ms hoặc 1.2s.", "error", offset))
        return None
    value = float(match.group(1))
    milliseconds = round(value * 1000 if match.group(2) == "s" else value)
    if not 0 <= milliseconds <= 10_000:
        issues.append(
            ExpressiveIssue(
                "invalid-pause",
                "[pause] must be between 0ms and 10s.",
                "error",
                offset,
            )
        )
        return None
    return milliseconds


def _parse_argument(raw: str) -> str:
    if not raw.strip():
        return ""
    try:
        parts = shlex.split(raw.strip(), posix=True)
    except ValueError:
        return raw.strip().strip('"\'')
    return " ".join(parts).strip()


def _apply_pronunciation_rules(
    text: str,
    language: str,
    rules: tuple[PronunciationRule, ...],
) -> str:
    resolved = text
    applicable = sorted(
        (rule for rule in rules if not rule.language or language == "auto" or rule.language == language),
        key=lambda rule: len(rule.source),
        reverse=True,
    )
    for rule in applicable:
        escaped = re.escape(rule.source)
        pattern = rf"(?<!\w){escaped}(?!\w)" if rule.whole_word else escaped
        flags = 0 if rule.case_sensitive else re.IGNORECASE
        resolved = re.sub(pattern, lambda _match: rule.replacement, resolved, flags=flags)
    return resolved


def _clamp_rate(value: float) -> float:
    return max(0.5, min(1.5, float(value)))

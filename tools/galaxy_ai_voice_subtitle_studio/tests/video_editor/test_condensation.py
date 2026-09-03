from __future__ import annotations

import json

import pytest

from app.video_editor.condensation import CueCondensationService, CueCondensationSpec
from app.voice.translator import AITranslationOptions


def _options() -> AITranslationOptions:
    return AITranslationOptions(
        source_language="vi",
        target_language="vi",
        provider="ollama",
        model="local-test",
        base_url="http://127.0.0.1:11434/v1",
    )


def test_condensation_returns_a_reviewable_proposal_without_mutating_source() -> None:
    calls: list[list[dict[str, str]]] = []

    def client(messages, _options):
        calls.append(messages)
        return json.dumps({"text": "Chúng ta về trước khi trời tối."}, ensure_ascii=False)

    spec = CueCondensationSpec(
        track_id="subtitle-1",
        cue_id="cue-2",
        text="Chúng ta cần phải quay trở về nhà trước khi trời tối.",
        language="vi",
        cue_duration_ms=1_000,
        audio_duration_ms=1_700,
    )

    result = CueCondensationService().propose(spec, _options(), client=client)

    assert result.original_text == spec.text
    assert result.proposed_text == "Chúng ta về trước khi trời tối."
    assert result.track_id == spec.track_id
    assert result.cue_id == spec.cue_id
    assert result.target_characters < len(spec.text)
    assert "không thêm thông tin" in calls[0][0]["content"].lower()


def test_condensation_rejects_a_proposal_that_is_not_shorter() -> None:
    spec = CueCondensationSpec(
        track_id="subtitle-1",
        cue_id="cue-2",
        text="Một câu cần rút gọn.",
        language="vi",
        cue_duration_ms=1_000,
        audio_duration_ms=1_700,
    )

    with pytest.raises(RuntimeError, match="ngắn hơn"):
        CueCondensationService().propose(
            spec,
            _options(),
            client=lambda _messages, _options: json.dumps({"text": spec.text}, ensure_ascii=False),
        )

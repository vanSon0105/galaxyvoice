from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceArchetype:
    archetype_id: str
    name: str
    use_case: str
    language: str
    instruct: str
    sample_text: str


_ARCHETYPES = (
    VoiceArchetype("warm-narrator", "Warm Narrator", "Narration", "en", "female, middle-aged, low pitch", "Every story begins with a voice worth following."),
    VoiceArchetype("documentary", "Documentary", "Narration", "en", "male, middle-aged, low pitch, british accent", "Across the valley, the first light reveals a forgotten road."),
    VoiceArchetype("news-anchor", "News Anchor", "News", "en", "female, young adult, moderate pitch, american accent", "Here are the stories shaping the day."),
    VoiceArchetype("trailer", "Cinema Trailer", "Video", "en", "male, middle-aged, very low pitch, american accent", "This summer, one decision changes everything."),
    VoiceArchetype("friendly-guide", "Friendly Guide", "Education", "en", "female, young adult, high pitch", "Let us walk through this together, one clear step at a time."),
    VoiceArchetype("calm-podcast", "Calm Podcast", "Podcast", "en", "male, young adult, moderate pitch, canadian accent", "Welcome back. Today we are slowing down to notice what matters."),
    VoiceArchetype("whisper-story", "Whisper Story", "Stories", "en", "female, young adult, low pitch, whisper", "Keep the lantern close. The forest remembers every footstep."),
    VoiceArchetype("game-hero", "Game Hero", "Character", "en", "male, young adult, high pitch, australian accent", "The gate is open. We move now."),
    VoiceArchetype("vi-narrator-f", "Vietnamese Narrator", "Narration", "vi", "female, middle-aged, low pitch", "Mỗi câu chuyện hay đều bắt đầu bằng một giọng kể đáng nhớ."),
    VoiceArchetype("vi-review-m", "Vietnamese Reviewer", "Video", "vi", "male, young adult, moderate pitch", "Hôm nay chúng ta sẽ cùng xem điều gì làm sản phẩm này khác biệt."),
    VoiceArchetype("zh-story-f", "Chinese Storyteller", "Stories", "zh", "女，中年，低音调", "很久以前，山谷里住着一位守灯人。"),
    VoiceArchetype("zh-sichuan-m", "Sichuan Character", "Character", "zh", "男，青年，中音调，四川话", "今天我们摆一摆这个有趣的故事。"),
)


def list_voice_archetypes(query: str = "", use_case: str = "") -> tuple[VoiceArchetype, ...]:
    needle = query.strip().casefold()
    category = use_case.strip().casefold()
    return tuple(
        item
        for item in _ARCHETYPES
        if (not needle or needle in f"{item.name} {item.use_case} {item.instruct}".casefold())
        and (not category or item.use_case.casefold() == category)
    )


def voice_archetype_categories() -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.use_case for item in _ARCHETYPES))

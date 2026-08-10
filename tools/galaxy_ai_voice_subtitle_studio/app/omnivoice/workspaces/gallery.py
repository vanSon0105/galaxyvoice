from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class VoiceArchetype:
    archetype_id: str
    name: str
    use_case: str
    language: str
    instruct: str
    sample_text: str
    gender: str = ""
    age: str = ""
    pitch: str = ""
    accent: str = ""
    style: str = ""
    featured: bool = True


_FEATURED_ARCHETYPES = (
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

_GENDERS = ("male", "female")
_AGES = ("child", "teenager", "young adult", "middle-aged", "elderly")
_PITCHES = (
    "very low pitch",
    "low pitch",
    "moderate pitch",
    "high pitch",
    "very high pitch",
)
_ACCENTS = (
    "american accent",
    "british accent",
    "australian accent",
    "chinese accent",
    "canadian accent",
    "indian accent",
    "korean accent",
    "portuguese accent",
    "russian accent",
    "japanese accent",
)
_DIALECTS = (
    "河南话",
    "陕西话",
    "四川话",
    "贵州话",
    "云南话",
    "桂林话",
    "济南话",
    "石家庄话",
    "甘肃话",
    "宁夏话",
    "青岛话",
    "东北话",
)
_PRUNED_PITCHES = {
    "child": {"very low pitch", "low pitch"},
    "teenager": {"very low pitch"},
    "elderly": {"very high pitch"},
}
_SAMPLES = {
    "Narration": "The road was quiet until a distant bell marked the beginning of the journey.",
    "Conversation": "Hey, it is good to see you. Let us catch up for a moment.",
    "Character": "The gate is open. This is our chance, so move now.",
    "Video": "Welcome back. Today we are looking at something genuinely useful.",
    "News": "Here are the stories and ideas shaping the day.",
    "Advertisement": "A simpler way to get your best work done starts today.",
    "Education": "Let us break this down into three clear and practical steps.",
}
_ZH_SAMPLE = "大家好，欢迎收听这段声音示范，希望你会喜欢这个声音。"


def _generated_archetypes() -> tuple[VoiceArchetype, ...]:
    items: list[VoiceArchetype] = []
    seen = {(item.instruct, item.language) for item in _FEATURED_ARCHETYPES}
    for gender in _GENDERS:
        for age in _AGES:
            for pitch in _PITCHES:
                if pitch in _PRUNED_PITCHES.get(age, set()):
                    continue
                for accent in ("", *_ACCENTS):
                    use_case = _use_case(age, pitch, bool(accent), False)
                    instruct = ", ".join(
                        value for value in (gender, age, pitch, accent) if value
                    )
                    key = (instruct, "en")
                    if key not in seen:
                        seen.add(key)
                        items.append(
                            _make_generated(
                                instruct,
                                language="en",
                                use_case=use_case,
                                name=_display_name(gender, age, pitch, accent),
                                sample_text=_SAMPLES[use_case],
                                gender=gender,
                                age=age,
                                pitch=pitch,
                                accent=accent,
                            )
                        )
                    if age in {"young adult", "middle-aged", "elderly"} and pitch in {
                        "low pitch",
                        "moderate pitch",
                    }:
                        whisper = f"{instruct}, whisper"
                        whisper_key = (whisper, "en")
                        if whisper_key not in seen:
                            seen.add(whisper_key)
                            items.append(
                                _make_generated(
                                    whisper,
                                    language="en",
                                    use_case="Narration",
                                    name=f"{_display_name(gender, age, pitch, accent)} · Whisper",
                                    sample_text=_SAMPLES["Narration"],
                                    gender=gender,
                                    age=age,
                                    pitch=pitch,
                                    accent=accent,
                                    style="whisper",
                                )
                            )
                for dialect in _DIALECTS:
                    instruct = ", ".join((gender, age, pitch, dialect))
                    key = (instruct, "zh")
                    if key in seen:
                        continue
                    seen.add(key)
                    use_case = _use_case(age, pitch, False, False)
                    items.append(
                        _make_generated(
                            instruct,
                            language="zh",
                            use_case=use_case,
                            name=f"{dialect} · {_display_name(gender, age, pitch, '')}",
                            sample_text=_ZH_SAMPLE,
                            gender=gender,
                            age=age,
                            pitch=pitch,
                            accent=dialect,
                        )
                    )
    return tuple(items)


def _make_generated(
    instruct: str,
    *,
    language: str,
    use_case: str,
    name: str,
    sample_text: str,
    gender: str,
    age: str,
    pitch: str,
    accent: str,
    style: str = "",
) -> VoiceArchetype:
    digest = hashlib.sha256(f"{language}|{instruct}".encode("utf-8")).hexdigest()[:12]
    return VoiceArchetype(
        archetype_id=f"generated-{digest}",
        name=name,
        use_case=use_case,
        language=language,
        instruct=instruct,
        sample_text=sample_text,
        gender=gender,
        age=age,
        pitch=pitch,
        accent=accent,
        style=style,
        featured=False,
    )


def _display_name(gender: str, age: str, pitch: str, accent: str) -> str:
    location = accent.replace(" accent", "").title() if accent else "Neutral"
    return " · ".join(
        (location, gender.title(), age.title(), pitch.replace(" pitch", "").title())
    )


def _use_case(age: str, pitch: str, has_accent: bool, whisper: bool) -> str:
    if whisper or (pitch in {"very low pitch", "low pitch"} and age in {"middle-aged", "elderly"}):
        return "Narration"
    if age in {"child", "teenager"} or pitch == "very high pitch":
        return "Character"
    if pitch == "high pitch" and age == "young adult":
        return "Video"
    if not has_accent and age == "middle-aged" and pitch == "moderate pitch":
        return "Education"
    if age == "young adult":
        return "Conversation"
    if age == "elderly":
        return "News"
    return "Advertisement"


_ARCHETYPES = _FEATURED_ARCHETYPES + _generated_archetypes()


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

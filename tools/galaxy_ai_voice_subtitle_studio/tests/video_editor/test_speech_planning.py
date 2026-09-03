from __future__ import annotations

from app.video_editor.speech import EditorSpeechCueSpec
from app.video_editor.speech_planning import ShortCueLimits, plan_short_cues


def _cue(
    item_id: str,
    start_ms: int,
    end_ms: int,
    text: str = "Mot cau ngan",
    *,
    track_id: str = "subtitle-1",
) -> EditorSpeechCueSpec:
    return EditorSpeechCueSpec(
        item_id,
        track_id,
        f"cue-{item_id}",
        start_ms,
        text,
        end_ms=end_ms,
    )


def test_planner_groups_adjacent_short_cues_and_preserves_order() -> None:
    cues = (
        _cue("1", 0, 900),
        _cue("2", 1_100, 2_000),
        _cue("3", 2_200, 3_000),
    )

    groups = plan_short_cues(cues)

    assert [[cue.item_id for cue in group.cues] for group in groups] == [["1", "2", "3"]]
    assert groups[0].clustered is True


def test_planner_enforces_each_cluster_boundary() -> None:
    cases = {
        "characters": (
            ShortCueLimits(max_cluster_chars=20),
            (_cue("1", 0, 900, "1234567890"), _cue("2", 1_000, 1_900, "abcdefghij")),
        ),
        "cue count": (
            ShortCueLimits(max_cluster_cues=2),
            (_cue("1", 0, 500), _cue("2", 600, 1_100), _cue("3", 1_200, 1_700)),
        ),
        "time span": (
            ShortCueLimits(max_cluster_span_ms=1_500),
            (_cue("1", 0, 900), _cue("2", 1_000, 2_000)),
        ),
        "join gap": (
            ShortCueLimits(max_join_gap_ms=100),
            (_cue("1", 0, 500), _cue("2", 700, 1_200)),
        ),
    }

    for name, (limits, cues) in cases.items():
        groups = plan_short_cues(cues, limits)
        assert len(groups) > 1, name


def test_planner_never_crosses_track_or_long_cue_boundaries() -> None:
    cues = (
        _cue("1", 0, 700),
        _cue("2", 800, 1_500, track_id="subtitle-2"),
        _cue("3", 1_600, 2_300, "x" * 80, track_id="subtitle-2"),
        _cue("4", 2_400, 3_100, track_id="subtitle-2"),
    )

    groups = plan_short_cues(cues)

    assert [[cue.item_id for cue in group.cues] for group in groups] == [
        ["1"],
        ["2"],
        ["3"],
        ["4"],
    ]
